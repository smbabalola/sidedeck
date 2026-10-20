"""SIM fills post only to the separate SIM books (ADR-003); research ledgers untouched."""
import ast
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from sidedeck.application import saxo_execution_pipeline as pipeline_module
from sidedeck.application.foundation import initialise_two_portfolios
from sidedeck.application.saxo_execution_history import BrokerExecution
from sidedeck.application.saxo_execution_pipeline import SaxoExecutionPipeline
from sidedeck.application.saxo_order_lifecycle import advance_lifecycle, create_lifecycle, lifecycle_state
from sidedeck.application.saxo_sim_submission import ensure_authorization_table
from sidedeck.domain.accounting import Ledger, fill_event
from sidedeck.domain.contracts import EventType, ExperimentManifest
from sidedeck.domain.sim_accounting import SimAccountingError
from sidedeck.infrastructure.saxo_sim_journal import SimJournalStore

AT = datetime(2026, 10, 19, 14, tzinfo=timezone.utc)
TA, AI = "saxo-sim:tradingagents", "saxo-sim:ai-trading"


def execution(status="FinalFill", quantity="1", execution_id="fill-1", price="40", fees="0.10",
              fees_currency="EUR", occurred_at="2026-10-19T14:00:00Z", order_id="broker-1",
              order_key="sofi-1", account_id="22866064"):
    return BrokerExecution(account_id, order_id, order_key, execution_id, status,
                           Decimal(quantity), Decimal(price), Decimal(fees), "USD", "EUR",
                           "USD", fees_currency, occurred_at)


def sim_db(tmp_path, name="p4.sqlite", *, open_books=True):
    db = str(tmp_path / name)
    if open_books:
        SimJournalStore(db).open_books(account_id="22866064", opened_at=AT - timedelta(hours=1),
                                       approval_ref="owner-decision-2026-10-20")
    return db


def authorize(db, *, order_key="sofi-1", strategy="tradingagents", account_id="22866064",
              broker_order_id="broker-1", quantity="1", book_id="default", fx="1.10"):
    """Seed the durable state the submitter writes on an acknowledged, signed order."""
    create_lifecycle(db, order_key)
    advance_lifecycle(db, order_key, "SUBMITTING")
    advance_lifecycle(db, order_key, "ACKNOWLEDGED", broker_order_id=broker_order_id,
                      broker_evidence=True)
    book = {"tradingagents": TA, "ai-trading": AI}[strategy] if book_id == "default" else book_id
    with sqlite3.connect(db) as connection:
        ensure_authorization_table(connection)
        connection.execute(
            "INSERT INTO saxo_execution_authorization (authorization_id, order_key, account_id, "
            "portfolio_id, request_sha256, broker_payload_sha256, risk_evidence_sha256, attestation, "
            "issued_by, expires_at, status, broker_order_id, quantity, requested_by, book_id, "
            "fx_usd_per_eur, fx_provider) VALUES (?, ?, ?, ?, 'r', 'b', 'k', 'sig', 'operator', "
            "'2026-10-19T14:05:00+00:00', 'CONSUMED', ?, ?, 'sidedeck-automation', ?, ?, 'licensed-fx')",
            ("auth-" + order_key, order_key, account_id, strategy, broker_order_id, quantity, book, fx))


def journal_count(db):
    with sqlite3.connect(db) as connection:
        return connection.execute("SELECT COUNT(*) FROM saxo_sim_journal").fetchone()[0]


def test_fill_posts_to_sim_book_with_eur_cash_usd_position_and_provenance(tmp_path):
    db = sim_db(tmp_path)
    authorize(db)
    pipeline = SaxoExecutionPipeline(db)
    first = pipeline.apply_buy_fill(execution(), order_key="sofi-1", account_id="22866064", now=AT)
    second = pipeline.apply_buy_fill(execution(), order_key="sofi-1", account_id="22866064", now=AT)
    assert (first.duplicate, second.duplicate) == (False, True)
    assert first.book_id == TA and first.settlement_eur == Decimal("36.3636")
    book = pipeline.ledger.replay(TA)
    assert book.cash_eur == Decimal("1000") - Decimal("36.3636") - Decimal("0.10")
    assert book.positions["US:SOFI"].quantity == Decimal("1")
    assert book.positions["US:SOFI"].cost_usd == Decimal("40")
    assert book.fees_eur == Decimal("0.10") and book.fill_count == 1
    assert pipeline.ledger.replay(AI).cash_eur == Decimal("1000")
    fill = [e for e in pipeline.ledger.events if e.broker_execution_id == "fill-1"][0]
    assert (fill.fx_usd_per_eur, fill.fx_provider, fill.settlement_source) == (
        Decimal("1.10"), "licensed-fx", "DERIVED_FX")
    assert (fill.fee_amount, fill.fee_currency, fill.approval_ref) == (
        Decimal("0.10"), "EUR", "auth-sofi-1")
    assert lifecycle_state(db, "sofi-1") == ("FILLED", "broker-1", 3)
    assert journal_count(db) == 3


def test_usd_fee_is_converted_with_the_approved_fx_not_a_caller_rate(tmp_path):
    db = sim_db(tmp_path)
    authorize(db, fx="1.25")
    applied = SaxoExecutionPipeline(db).apply_buy_fill(
        execution(fees="0.50", fees_currency="USD"), order_key="sofi-1", account_id="22866064", now=AT)
    assert applied.fee_eur == Decimal("0.4000") and applied.settlement_eur == Decimal("32.0000")


def test_attribution_comes_from_the_signed_authorization_book(tmp_path):
    db = sim_db(tmp_path)
    authorize(db, strategy="ai-trading")
    pipeline = SaxoExecutionPipeline(db)
    applied = pipeline.apply_buy_fill(execution(), order_key="sofi-1", account_id="22866064", now=AT)
    assert applied.book_id == AI
    assert pipeline.ledger.replay(TA).fill_count == 0


@pytest.mark.parametrize("book_id", [None, "saxo-sim:ai-trading", "saxo-sim:unattributed"])
def test_authorization_book_must_match_its_strategy(tmp_path, book_id):
    db = sim_db(tmp_path)
    authorize(db, book_id=book_id)
    with pytest.raises(SimAccountingError, match="valid SIM strategy book"):
        SaxoExecutionPipeline(db).apply_buy_fill(execution(), order_key="sofi-1",
                                                 account_id="22866064", now=AT)
    assert journal_count(db) == 2


def test_fill_requires_consumed_authorization_matching_account_and_order(tmp_path):
    db = sim_db(tmp_path)
    create_lifecycle(db, "sofi-1")
    advance_lifecycle(db, "sofi-1", "SUBMITTING")
    advance_lifecycle(db, "sofi-1", "ACKNOWLEDGED", broker_order_id="broker-1", broker_evidence=True)
    pipeline = SaxoExecutionPipeline(db)
    with pytest.raises(SimAccountingError, match="consumed operator authorization"):
        pipeline.apply_buy_fill(execution(), order_key="sofi-1", account_id="22866064", now=AT)
    with pytest.raises(SimAccountingError, match="matched"):
        pipeline.apply_buy_fill(execution(), order_key="sofi-1", account_id="other", now=AT)
    assert journal_count(db) == 2


def test_quantity_limit_comes_from_the_authorization(tmp_path):
    db = sim_db(tmp_path)
    authorize(db, quantity="1")
    with pytest.raises(SimAccountingError, match="exceeds authorized"):
        SaxoExecutionPipeline(db).apply_buy_fill(execution(status="Fill", quantity="2"),
                                                 order_key="sofi-1", account_id="22866064", now=AT)


def test_partial_then_final_fill_and_overfill_rejected(tmp_path):
    db = sim_db(tmp_path)
    authorize(db, quantity="2")
    pipeline = SaxoExecutionPipeline(db)
    pipeline.apply_buy_fill(execution(status="Fill", execution_id="f1"), order_key="sofi-1",
                            account_id="22866064", now=AT)
    assert lifecycle_state(db, "sofi-1")[0] == "PARTIAL"
    with pytest.raises(SimAccountingError, match="quantity"):
        pipeline.apply_buy_fill(execution(execution_id="f2", quantity="2"), order_key="sofi-1",
                                account_id="22866064", now=AT)
    pipeline.apply_buy_fill(execution(execution_id="f3"), order_key="sofi-1",
                            account_id="22866064", now=AT)
    assert lifecycle_state(db, "sofi-1")[0] == "FILLED"
    assert pipeline.ledger.replay(TA).positions["US:SOFI"].quantity == Decimal("2")


def test_usd_200_position_cap_and_eur_allocation_are_enforced(tmp_path):
    db = sim_db(tmp_path)
    authorize(db, quantity="6")
    pipeline = SaxoExecutionPipeline(db)
    for index in range(5):
        pipeline.apply_buy_fill(execution(status="Fill", execution_id=f"f{index}"),
                                order_key="sofi-1", account_id="22866064", now=AT)
    with pytest.raises(SimAccountingError, match="USD 200"):
        pipeline.apply_buy_fill(execution(execution_id="f5"), order_key="sofi-1",
                                account_id="22866064", now=AT)
    db2 = sim_db(tmp_path, "cash.sqlite")
    authorize(db2)
    with pytest.raises(SimAccountingError, match="EUR allocation"):
        SaxoExecutionPipeline(db2).apply_buy_fill(execution(fees="990"), order_key="sofi-1",
                                                  account_id="22866064", now=AT)
    assert journal_count(db2) == 2


def test_execution_id_reuse_with_different_payload_is_rejected(tmp_path):
    db = sim_db(tmp_path)
    authorize(db)
    pipeline = SaxoExecutionPipeline(db)
    pipeline.apply_buy_fill(execution(), order_key="sofi-1", account_id="22866064", now=AT)
    with pytest.raises(SimAccountingError, match="different economic payload"):
        pipeline.apply_buy_fill(execution(price="41"), order_key="sofi-1",
                                account_id="22866064", now=AT)
    assert journal_count(db) == 3


def test_frozen_book_or_account_blocks_new_fills_only_where_frozen(tmp_path):
    db = sim_db(tmp_path)
    authorize(db)
    authorize(db, order_key="sofi-2", strategy="ai-trading", broker_order_id="broker-2")
    store = SimJournalStore(db)
    store.freeze((TA,), scope="BOOK", reason="test mismatch", at=AT)
    pipeline = SaxoExecutionPipeline(db)
    with pytest.raises(SimAccountingError, match="book is frozen"):
        pipeline.apply_buy_fill(execution(), order_key="sofi-1", account_id="22866064", now=AT)
    pipeline.apply_buy_fill(execution(execution_id="fill-2", order_id="broker-2", order_key="sofi-2"),
                            order_key="sofi-2", account_id="22866064", now=AT)
    store.freeze((TA, AI, "saxo-sim:unattributed"), scope="ACCOUNT", reason="unexplained", at=AT)
    authorize(db, order_key="sofi-3", strategy="ai-trading", broker_order_id="broker-3")
    with pytest.raises(SimAccountingError, match="account-wide"):
        pipeline.apply_buy_fill(execution(execution_id="fill-3", order_id="broker-3",
                                          order_key="sofi-3"),
                                order_key="sofi-3", account_id="22866064", now=AT)


def test_crash_after_commit_is_recovered_deterministically(tmp_path, monkeypatch):
    db = sim_db(tmp_path)
    authorize(db)
    original = pipeline_module.advance_lifecycle

    def crash(*args, **kwargs):
        raise RuntimeError("simulated crash after journal commit")

    monkeypatch.setattr(pipeline_module, "advance_lifecycle", crash)
    with pytest.raises(RuntimeError, match="simulated crash"):
        SaxoExecutionPipeline(db).apply_buy_fill(execution(), order_key="sofi-1",
                                                 account_id="22866064", now=AT)
    assert lifecycle_state(db, "sofi-1")[0] == "ACKNOWLEDGED"
    monkeypatch.setattr(pipeline_module, "advance_lifecycle", original)
    restarted = SaxoExecutionPipeline(db)
    assert restarted.recover() == 1
    assert restarted.recover() == 1
    assert lifecycle_state(db, "sofi-1") == ("FILLED", "broker-1", 3)
    state = restarted.ledger.replay(TA)
    assert state.positions["US:SOFI"].quantity == Decimal("1") and journal_count(db) == 3


def test_crash_before_commit_leaves_nothing_and_retry_posts_once(tmp_path, monkeypatch):
    db = sim_db(tmp_path)
    authorize(db)

    def crash(*args, **kwargs):
        raise RuntimeError("simulated crash before commit")

    monkeypatch.setattr(SimJournalStore, "record_fill", crash)
    with pytest.raises(RuntimeError):
        SaxoExecutionPipeline(db).apply_buy_fill(execution(), order_key="sofi-1",
                                                 account_id="22866064", now=AT)
    assert journal_count(db) == 2
    monkeypatch.undo()
    applied = SaxoExecutionPipeline(db).apply_buy_fill(execution(), order_key="sofi-1",
                                                       account_id="22866064", now=AT)
    assert not applied.duplicate and journal_count(db) == 3


def test_concurrent_duplicate_delivery_posts_exactly_once(tmp_path):
    db = sim_db(tmp_path)
    authorize(db)
    pipelines = [SaxoExecutionPipeline(db) for _ in range(4)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda p: p.apply_buy_fill(
            execution(), order_key="sofi-1", account_id="22866064", now=AT), pipelines))
    assert sorted(r.duplicate for r in results) == [False, True, True, True]
    assert journal_count(db) == 3
    assert SaxoExecutionPipeline(db).ledger.replay(TA).positions["US:SOFI"].quantity == Decimal("1")


def test_lifecycle_race_is_tolerated_only_when_the_other_worker_reached_the_target(
        tmp_path, monkeypatch):
    """Deterministic version of the CI #456 race: state read is stale at write time."""
    db = sim_db(tmp_path)
    authorize(db)
    pipeline = SaxoExecutionPipeline(db)
    stale = ("ACKNOWLEDGED", "broker-1", 1)
    real_state = pipeline_module.lifecycle_state
    calls = {"n": 0}

    def first_read_is_stale(path, key):
        calls["n"] += 1
        return stale if calls["n"] == 1 else real_state(path, key)

    advance_lifecycle(db, "sofi-1", "FILLED", broker_order_id="broker-1", broker_evidence=True)
    monkeypatch.setattr(pipeline_module, "lifecycle_state", first_read_is_stale)
    pipeline._advance_lifecycle("sofi-1", "broker-1", final=True)        # tolerated: already FILLED
    assert real_state(db, "sofi-1")[0] == "FILLED"
    db2 = sim_db(tmp_path, "cancelled.sqlite")
    authorize(db2)
    advance_lifecycle(db2, "sofi-1", "CANCELLED")
    calls["n"] = 0
    with pytest.raises(Exception, match="unapproved lifecycle transition"):
        SaxoExecutionPipeline(db2)._advance_lifecycle("sofi-1", "broker-1", final=True)


def test_replay_is_chronological_and_corruption_is_rejected(tmp_path):
    db = sim_db(tmp_path)
    authorize(db, quantity="2")
    pipeline = SaxoExecutionPipeline(db)
    pipeline.apply_buy_fill(execution(status="Fill", execution_id="zz-late",
                                      occurred_at="2026-10-19T14:02:00Z"),
                            order_key="sofi-1", account_id="22866064", now=AT)
    pipeline.apply_buy_fill(execution(execution_id="aa-early", occurred_at="2026-10-19T14:01:00Z"),
                            order_key="sofi-1", account_id="22866064", now=AT)
    keys = [e.idempotency_key for e in SaxoExecutionPipeline(db).ledger.events][-2:]
    assert keys == ["saxo:aa-early", "saxo:zz-late"]
    with sqlite3.connect(db) as connection:
        connection.execute("UPDATE saxo_sim_journal SET payload=replace(payload, '\"40\"', '\"4\"') "
                           "WHERE broker_execution_id='aa-early'")
    with pytest.raises(SimAccountingError, match="hash mismatch"):
        SaxoExecutionPipeline(db)


def test_naive_timestamp_and_unopened_books_are_rejected(tmp_path):
    db = sim_db(tmp_path)
    authorize(db)
    with pytest.raises(SimAccountingError, match="timezone"):
        SaxoExecutionPipeline(db).apply_buy_fill(execution(occurred_at="2026-10-19T14:00:00"),
                                                 order_key="sofi-1", account_id="22866064", now=AT)
    unopened = sim_db(tmp_path, "unopened.sqlite", open_books=False)
    authorize(unopened)
    with pytest.raises(SimAccountingError, match="no allocation|not opened"):
        SaxoExecutionPipeline(unopened).apply_buy_fill(execution(), order_key="sofi-1",
                                                       account_id="22866064", now=AT)


def test_legacy_research_ledger_fill_rows_block_the_pipeline(tmp_path):
    db = sim_db(tmp_path)
    SaxoExecutionPipeline(db)
    with sqlite3.connect(db) as connection:
        connection.execute("INSERT INTO saxo_execution_recovery (execution_id, order_key, portfolio_id, "
                           "event_payload, event_sha256, status, broker_order_id, fill_status) "
                           "VALUES ('x', 'sofi-1', 'tradingagents', '{}', 'h', 'POSTED', 'b', 'FinalFill')")
    with pytest.raises(SimAccountingError, match="owner review"):
        SaxoExecutionPipeline(db)


def test_research_ledger_and_journal_reject_saxo_sim_events(tmp_path):
    from sidedeck.infrastructure.database import create_database, create_schema, save_events
    research = initialise_two_portfolios(ExperimentManifest(
        experiment_id="p4", configuration_revision="r1", created_at=AT,
        instruments=("US:SOFI",), data_policy="licensed"), AT)
    event = fill_event("tradingagents", "saxo:fill-1", EventType.BUY_FILL, "US:SOFI",
                       Decimal("1"), Decimal("40"), AT)
    with pytest.raises(ValueError, match="SIM books"):
        research.append(event)
    with pytest.raises(ValueError, match="SIM books"):
        Ledger().append(event)
    engine = create_database(f"sqlite:///{tmp_path / 'research.db'}")
    create_schema(engine)
    with pytest.raises(ValueError, match="SIM books"):
        save_events(engine, [event])
    engine.dispose()
    assert research.replay("tradingagents").cash == Decimal("1000")


def test_saxo_and_sim_modules_cannot_reach_alpaca_and_alpaca_reconciliation_is_unchanged():
    root = Path(__file__).resolve().parents[1] / "src" / "sidedeck"
    modules = (list(root.glob("application/saxo_*.py")) + list(root.glob("infrastructure/saxo_*.py"))
               + [root / "domain" / "sim_accounting.py"])

    def imports(path):
        names = []
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names += [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module)
        return names

    for module in modules:
        assert not any("alpaca" in name for name in imports(module)), module.name
    alpaca_reconciliation = imports(root / "application" / "reconciliation.py")
    assert not any("saxo" in name or "sim_accounting" in name for name in alpaca_reconciliation)
    assert not any(name.endswith("domain.accounting")
                   for name in imports(root / "application" / "saxo_execution_pipeline.py"))
