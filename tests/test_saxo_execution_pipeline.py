from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import pytest

from sidedeck.application.saxo_execution_history import BrokerExecution
from sidedeck.application.saxo_execution_pipeline import SaxoExecutionPipeline
from sidedeck.application.saxo_market_data import FxSnapshot
from sidedeck.application.saxo_order_lifecycle import advance_lifecycle, create_lifecycle, lifecycle_state
from sidedeck.application.saxo_sim_submission import ensure_authorization_table
from sidedeck.application.foundation import initialise_two_portfolios
from sidedeck.domain.contracts import ExperimentManifest


def execution(status="FinalFill", quantity="1", execution_id="fill-1",
              occurred_at="2026-10-19T14:00:00Z", order_id="broker-1"):
    return BrokerExecution("22866064", order_id, "sofi-1", execution_id, status,
                           Decimal(quantity), Decimal("40"), Decimal("0.10"), "USD", "EUR",
                           "USD", "EUR",
                           occurred_at)


def authorize(db, *, order_key="sofi-1", portfolio_id="tradingagents", account_id="22866064",
              broker_order_id="broker-1", quantity="1"):
    """Seed the durable CONSUMED authorization the submitter writes on acknowledgement."""
    import sqlite3
    with sqlite3.connect(db) as connection:
        ensure_authorization_table(connection)
        connection.execute(
            "INSERT INTO saxo_execution_authorization (authorization_id, order_key, account_id, "
            "portfolio_id, request_sha256, broker_payload_sha256, risk_evidence_sha256, attestation, "
            "issued_by, expires_at, status, broker_order_id, quantity, requested_by) "
            "VALUES (?, ?, ?, ?, 'r', 'b', 'k', 'sig', 'operator', '2026-10-19T14:05:00+00:00', "
            "'CONSUMED', ?, ?, 'sidedeck-automation')",
            ("auth-" + order_key, order_key, account_id, portfolio_id, broker_order_id, quantity))


def test_fill_is_converted_posted_and_deduplicated(tmp_path):
    at = datetime(2026, 10, 19, 14, tzinfo=timezone.utc)
    ledger = initialise_two_portfolios(
        ExperimentManifest(experiment_id="p4", configuration_revision="r1",
                           created_at=at, instruments=("US:SOFI",), data_policy="licensed"), at)
    db = tmp_path / "p4.sqlite"
    create_lifecycle(db, "sofi-1")
    advance_lifecycle(db, "sofi-1", "SUBMITTING")
    advance_lifecycle(db, "sofi-1", "ACKNOWLEDGED", broker_order_id="broker-1",
                      broker_evidence=True)
    authorize(db, quantity="1")
    pipeline = SaxoExecutionPipeline(str(db), ledger)
    fx = FxSnapshot("fx", "EUR/USD", Decimal("1.10"), at, at, "verified")
    first = pipeline.apply_buy_fill(execution(), order_key="sofi-1",
                                    portfolio_id="tradingagents", fx=fx,
                                    account_id="22866064", now=at)
    second = pipeline.apply_buy_fill(execution(), order_key="sofi-1",
                                     portfolio_id="tradingagents", fx=fx,
                                     account_id="22866064", now=at)
    assert not first.duplicate and second.duplicate
    state = ledger.replay("tradingagents")
    assert state.positions["US:SOFI"].quantity == Decimal("1")
    assert state.cash == Decimal("1000") - Decimal("40") - Decimal("0.11")
    assert lifecycle_state(db, "sofi-1") == ("FILLED", "broker-1", 3)


def test_execution_cannot_cross_portfolio_or_account(tmp_path):
    at = datetime(2026, 10, 19, 14, tzinfo=timezone.utc)
    ledger = initialise_two_portfolios(
        ExperimentManifest(experiment_id="p4", configuration_revision="r1",
                           created_at=at, instruments=("US:SOFI",), data_policy="licensed"), at)
    pipeline = SaxoExecutionPipeline(str(tmp_path / "p4.sqlite"), ledger)
    fx = FxSnapshot("fx", "EUR/USD", Decimal("1.10"), at, at, "verified")
    try:
        pipeline.apply_buy_fill(execution(), order_key="sofi-1", portfolio_id="ai-trading",
                                fx=fx, account_id="wrong", now=at)
    except ValueError as exc:
        assert "matched" in str(exc)
    else:
        raise AssertionError("cross-account execution was accepted")


def test_pending_fill_recovers_after_ledger_failure(tmp_path):
    at = datetime(2026, 10, 19, 14, tzinfo=timezone.utc)
    original = initialise_two_portfolios(
        ExperimentManifest(experiment_id="p4", configuration_revision="r1",
                           created_at=at, instruments=("US:SOFI",), data_policy="licensed"), at)
    db = tmp_path / "recover.sqlite"
    create_lifecycle(db, "sofi-1")
    advance_lifecycle(db, "sofi-1", "SUBMITTING")
    advance_lifecycle(db, "sofi-1", "ACKNOWLEDGED", broker_order_id="broker-1",
                      broker_evidence=True)
    authorize(db, quantity="1")
    pipeline = SaxoExecutionPipeline(str(db), original)
    real_append = original.append

    def crash(event):
        raise RuntimeError("simulated ledger failure")

    original.append = crash  # type: ignore[method-assign]
    fx = FxSnapshot("fx", "EUR/USD", Decimal("1.10"), at, at, "verified")
    try:
        pipeline.apply_buy_fill(execution(), order_key="sofi-1", portfolio_id="tradingagents",
                                fx=fx, account_id="22866064", now=at)
    except RuntimeError:
        pass
    else:
        raise AssertionError("simulated ledger failure did not propagate")
    recovered_ledger = initialise_two_portfolios(
        ExperimentManifest(experiment_id="p4", configuration_revision="r1",
                           created_at=at, instruments=("US:SOFI",), data_policy="licensed"), at)
    recovered = SaxoExecutionPipeline(str(db), recovered_ledger)
    recovered_count = recovered.recover()
    assert recovered_count == 1
    assert recovered_ledger.replay("tradingagents").positions["US:SOFI"].quantity == Decimal("1")
    assert lifecycle_state(db, "sofi-1") == ("FILLED", "broker-1", 3)
    assert real_append is not None


def test_successful_posting_reloads_all_economic_state_after_restart(tmp_path):
    at = datetime(2026, 10, 19, 14, tzinfo=timezone.utc)
    manifest = ExperimentManifest(experiment_id="p4", configuration_revision="r1",
                                  created_at=at, instruments=("US:SOFI",), data_policy="licensed")
    ledger = initialise_two_portfolios(manifest, at)
    db = tmp_path / "restart.sqlite"
    create_lifecycle(db, "sofi-1")
    advance_lifecycle(db, "sofi-1", "SUBMITTING")
    advance_lifecycle(db, "sofi-1", "ACKNOWLEDGED", broker_order_id="broker-1", broker_evidence=True)
    authorize(db, quantity="1")
    fx = FxSnapshot("fx", "EUR/USD", Decimal("1.10"), at, at, "verified")
    SaxoExecutionPipeline(str(db), ledger).apply_buy_fill(
        execution(), order_key="sofi-1", portfolio_id="tradingagents", fx=fx,
        account_id="22866064", now=at)
    restarted_ledger = initialise_two_portfolios(manifest, at)
    restarted = SaxoExecutionPipeline(str(db), restarted_ledger)
    assert restarted.recover() == 1
    state = restarted_ledger.replay("tradingagents")
    assert state.cash == Decimal("959.89")
    assert state.positions["US:SOFI"].quantity == Decimal("1")
    assert state.positions["US:SOFI"].cost_basis == Decimal("40")
    assert state.fees == Decimal("0.11")
    assert restarted.recover() == 0
    assert len(restarted_ledger.events) == 3


def test_recovery_is_concurrent_and_final_fill_cannot_overfill(tmp_path):
    at = datetime(2026, 10, 19, 14, tzinfo=timezone.utc)
    manifest = ExperimentManifest(experiment_id="p4", configuration_revision="r1",
                                  created_at=at, instruments=("US:SOFI",), data_policy="licensed")
    source = initialise_two_portfolios(manifest, at)
    db = tmp_path / "concurrent.sqlite"
    create_lifecycle(db, "sofi-1")
    advance_lifecycle(db, "sofi-1", "SUBMITTING")
    advance_lifecycle(db, "sofi-1", "ACKNOWLEDGED", broker_order_id="broker-1", broker_evidence=True)
    authorize(db, quantity="2")
    fx = FxSnapshot("fx", "EUR/USD", Decimal("1.10"), at, at, "verified")
    pipeline = SaxoExecutionPipeline(str(db), source)
    pipeline.apply_buy_fill(execution(status="Fill", execution_id="fill-part", quantity="1"),
                            order_key="sofi-1", portfolio_id="tradingagents", fx=fx,
                            account_id="22866064", now=at)
    with pytest.raises(ValueError, match="quantity"):
        pipeline.apply_buy_fill(execution(status="FinalFill", execution_id="fill-over", quantity="2"),
                                order_key="sofi-1", portfolio_id="tradingagents", fx=fx,
                                account_id="22866064", now=at)
    ledgers = [initialise_two_portfolios(manifest, at) for _ in range(2)]
    pipelines = [SaxoExecutionPipeline(str(db), item) for item in ledgers]
    with ThreadPoolExecutor(max_workers=2) as pool:
        counts = list(pool.map(lambda item: item.recover(), pipelines))
    assert counts == [1, 1]
    assert all(item.replay("tradingagents").positions["US:SOFI"].quantity == Decimal("1")
               for item in ledgers)


def test_recovery_is_chronological_and_rejects_broker_identity_mismatch(tmp_path):
    at = datetime(2026, 10, 19, 14, tzinfo=timezone.utc)
    manifest = ExperimentManifest(experiment_id="p4", configuration_revision="r1",
                                  created_at=at, instruments=("US:SOFI",), data_policy="licensed")
    ledger = initialise_two_portfolios(manifest, at)
    db = tmp_path / "chronological.sqlite"
    create_lifecycle(db, "sofi-1")
    advance_lifecycle(db, "sofi-1", "SUBMITTING")
    advance_lifecycle(db, "sofi-1", "ACKNOWLEDGED", broker_order_id="broker-1", broker_evidence=True)
    authorize(db, quantity="2")
    fx = FxSnapshot("fx", "EUR/USD", Decimal("1.10"), at, at, "verified")
    pipeline = SaxoExecutionPipeline(str(db), ledger)
    pipeline.apply_buy_fill(execution(status="Fill", execution_id="zz-old",
                                      occurred_at="2026-10-19T14:01:00Z"),
                            order_key="sofi-1", portfolio_id="tradingagents", fx=fx,
                            account_id="22866064", now=at)
    pipeline.apply_buy_fill(execution(status="FinalFill", execution_id="aa-new",
                                      occurred_at="2026-10-19T14:02:00Z"),
                            order_key="sofi-1", portfolio_id="tradingagents", fx=fx,
                            account_id="22866064", now=at)
    with pytest.raises(ValueError, match="broker order ID"):
        pipeline.apply_buy_fill(execution(execution_id="bad-order", order_id="broker-wrong"),
                                order_key="sofi-1", portfolio_id="tradingagents", fx=fx,
                                account_id="22866064", now=at)
    restarted_ledger = initialise_two_portfolios(manifest, at)
    restarted = SaxoExecutionPipeline(str(db), restarted_ledger)
    assert restarted.recover() == 2
    assert [event.idempotency_key for event in restarted_ledger.events[-2:]] == [
        "saxo:zz-old", "saxo:aa-new"]
    state = restarted_ledger.replay("tradingagents")
    assert state.positions["US:SOFI"].quantity == Decimal("2")
    assert state.cash == Decimal("919.78")
    assert lifecycle_state(db, "sofi-1")[0] == "FILLED"


def test_corrupt_persisted_event_is_rejected_before_replay(tmp_path):
    at = datetime(2026, 10, 19, 14, tzinfo=timezone.utc)
    manifest = ExperimentManifest(experiment_id="p4", configuration_revision="r1",
                                  created_at=at, instruments=("US:SOFI",), data_policy="licensed")
    ledger = initialise_two_portfolios(manifest, at)
    db = tmp_path / "corrupt.sqlite"
    create_lifecycle(db, "sofi-1")
    advance_lifecycle(db, "sofi-1", "SUBMITTING")
    advance_lifecycle(db, "sofi-1", "ACKNOWLEDGED", broker_order_id="broker-1", broker_evidence=True)
    authorize(db, quantity="1")
    fx = FxSnapshot("fx", "EUR/USD", Decimal("1.10"), at, at, "verified")
    SaxoExecutionPipeline(str(db), ledger).apply_buy_fill(
        execution(), order_key="sofi-1", portfolio_id="tradingagents", fx=fx,
        account_id="22866064", now=at)
    import sqlite3
    with sqlite3.connect(db) as connection:
        connection.execute("UPDATE saxo_execution_recovery SET event_payload='corrupt'")
    with pytest.raises(ValueError, match="hash"):
        SaxoExecutionPipeline(str(db), initialise_two_portfolios(manifest, at)).recover()


def _acknowledged_db(tmp_path, name):
    db = tmp_path / name
    create_lifecycle(db, "sofi-1")
    advance_lifecycle(db, "sofi-1", "SUBMITTING")
    advance_lifecycle(db, "sofi-1", "ACKNOWLEDGED", broker_order_id="broker-1", broker_evidence=True)
    return db


def _ledger(at):
    return initialise_two_portfolios(
        ExperimentManifest(experiment_id="p4", configuration_revision="r1",
                           created_at=at, instruments=("US:SOFI",), data_policy="licensed"), at)


def test_fill_requires_consumed_operator_authorization(tmp_path):
    at = datetime(2026, 10, 19, 14, tzinfo=timezone.utc)
    db = _acknowledged_db(tmp_path, "unauthorized.sqlite")
    ledger = _ledger(at)
    fx = FxSnapshot("fx", "EUR/USD", Decimal("1.10"), at, at, "verified")
    with pytest.raises(ValueError, match="consumed operator authorization"):
        SaxoExecutionPipeline(str(db), ledger).apply_buy_fill(
            execution(), order_key="sofi-1", portfolio_id="tradingagents", fx=fx,
            account_id="22866064", now=at)
    assert ledger.replay("tradingagents").cash == Decimal("1000")


def test_fill_cannot_post_to_a_portfolio_other_than_the_authorized_one(tmp_path):
    at = datetime(2026, 10, 19, 14, tzinfo=timezone.utc)
    db = _acknowledged_db(tmp_path, "separation.sqlite")
    authorize(db, portfolio_id="tradingagents")
    ledger = _ledger(at)
    fx = FxSnapshot("fx", "EUR/USD", Decimal("1.10"), at, at, "verified")
    with pytest.raises(ValueError, match="portfolio or account differs"):
        SaxoExecutionPipeline(str(db), ledger).apply_buy_fill(
            execution(), order_key="sofi-1", portfolio_id="ai-trading", fx=fx,
            account_id="22866064", now=at)
    assert ledger.replay("ai-trading").cash == Decimal("1000")
    assert ledger.replay("tradingagents").cash == Decimal("1000")


def test_fill_quantity_comes_from_the_durable_authorization_not_the_caller(tmp_path):
    at = datetime(2026, 10, 19, 14, tzinfo=timezone.utc)
    db = _acknowledged_db(tmp_path, "quantity.sqlite")
    authorize(db, quantity="1")
    fx = FxSnapshot("fx", "EUR/USD", Decimal("1.10"), at, at, "verified")
    with pytest.raises(ValueError, match="exceeds authorized"):
        SaxoExecutionPipeline(str(db), _ledger(at)).apply_buy_fill(
            execution(status="Fill", quantity="2"), order_key="sofi-1",
            portfolio_id="tradingagents", fx=fx, account_id="22866064", now=at)


def test_naive_execution_timestamp_is_rejected(tmp_path):
    at = datetime(2026, 10, 19, 14, tzinfo=timezone.utc)
    db = _acknowledged_db(tmp_path, "naive.sqlite")
    authorize(db)
    fx = FxSnapshot("fx", "EUR/USD", Decimal("1.10"), at, at, "verified")
    with pytest.raises(ValueError, match="timezone"):
        SaxoExecutionPipeline(str(db), _ledger(at)).apply_buy_fill(
            execution(occurred_at="2026-10-19T14:00:00"), order_key="sofi-1",
            portfolio_id="tradingagents", fx=fx, account_id="22866064", now=at)


def test_saxo_execution_modules_cannot_reach_alpaca_paper_accounts():
    import ast
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "src" / "sidedeck"
    saxo_modules = list(root.glob("application/saxo_*.py")) + list(root.glob("infrastructure/saxo_*.py"))
    assert saxo_modules
    for module in saxo_modules:
        tree = ast.parse(module.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            assert not any("alpaca" in name for name in names), module.name
