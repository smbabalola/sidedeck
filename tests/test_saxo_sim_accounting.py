"""SIM books, reconciliation freezing and separate reporting (ADR-003, owner decisions 2026-10-20)."""
from datetime import timedelta
from decimal import Decimal

import pytest

from sidedeck.application.saxo_execution_pipeline import SaxoExecutionPipeline
from sidedeck.application.saxo_sim_reconciliation import (
    SimBrokerEvidence, apply_reconciliation, reconcile_sim_account, release_freeze,
)
from sidedeck.application.saxo_sim_report import sim_performance_report
from sidedeck.domain.sim_accounting import (
    SIM_BOOKS, UNATTRIBUTED_BOOK, SettlementSource, SimAccountingError, SimEvent, SimEventType,
    SimLedger,
)
from sidedeck.infrastructure.saxo_sim_journal import SimJournalStore
from test_saxo_execution_pipeline import AI, AT, TA, authorize, execution, journal_count, sim_db

SOFI = 23241352
ACCOUNT = "22866064"


def allocation(book, amount="1000", key="allocation:initial"):
    return SimEvent(book_id=book, idempotency_key=key, event_type=SimEventType.SIM_ALLOCATION,
                    occurred_at=AT, allocation_eur=Decimal(amount), approval_ref="owner")


def fill(book=TA, **changes):
    values = dict(book_id=book, idempotency_key="saxo:x", event_type=SimEventType.SIM_BUY_FILL,
                  occurred_at=AT, order_key="o", broker_execution_id="x", instrument_id="US:SOFI",
                  uic=SOFI, quantity=Decimal("1"), price_usd=Decimal("40"),
                  fx_usd_per_eur=Decimal("1.10"), fx_provider="fx",
                  settlement_eur=Decimal("36.36"), settlement_source=SettlementSource.DERIVED_FX,
                  fee_amount=Decimal("0"), fee_currency="EUR", fee_eur=Decimal("0"),
                  approval_ref="auth")
    values.update(changes)
    return SimEvent(**values)


# --- SimLedger rules -------------------------------------------------------

def test_allocation_is_exactly_eur_1000_once_and_never_to_unattributed():
    ledger = SimLedger()
    with pytest.raises(SimAccountingError, match="EUR 1,000"):
        ledger.append(allocation(TA, "1500"))
    assert ledger.append(allocation(TA))
    assert not ledger.append(allocation(TA))                       # exact replay is idempotent
    with pytest.raises(SimAccountingError, match="top-ups"):
        ledger.append(allocation(TA, key="allocation:top-up"))
    with pytest.raises(SimAccountingError, match="unattributed"):
        allocation(UNATTRIBUTED_BOOK)
    with pytest.raises(SimAccountingError, match="idempotency"):
        ledger.append(SimEvent(book_id=TA, idempotency_key="allocation:initial",
                               event_type=SimEventType.SIM_ALLOCATION, occurred_at=AT,
                               allocation_eur=Decimal("1000"), approval_ref="other"))


def test_sim_ledger_refuses_research_portfolios_and_unprovenanced_fills():
    for research_portfolio in ("tradingagents", "ai-trading"):
        with pytest.raises(SimAccountingError, match="not a Saxo SIM book"):
            allocation(research_portfolio)
    with pytest.raises(SimAccountingError, match="provenance"):
        fill(fx_provider=None)
    with pytest.raises(SimAccountingError, match="provenance"):
        fill(fee_currency=None)
    with pytest.raises(SimAccountingError, match="unattributed"):
        fill(book=UNATTRIBUTED_BOOK)
    with pytest.raises(SimAccountingError, match="fee currency"):
        fill(fee_currency="GBP")
    ledger = SimLedger()
    with pytest.raises(SimAccountingError, match="no allocation"):
        ledger.append(fill())


def test_store_opens_three_books_once_for_one_account(tmp_path):
    db = sim_db(tmp_path)
    store = SimJournalStore(db)
    assert not store.open_books(account_id=ACCOUNT, opened_at=AT, approval_ref="owner")
    with pytest.raises(SimAccountingError, match="different account"):
        store.open_books(account_id="another", opened_at=AT, approval_ref="owner")
    statuses = store.statuses()
    assert set(statuses) == set(SIM_BOOKS) and {s.status for s in statuses.values()} == {"OPEN"}
    ledger = store.load_ledger()
    assert [ledger.replay(b).allocation_eur for b in (TA, AI, UNATTRIBUTED_BOOK)] == [
        Decimal("1000"), Decimal("1000"), Decimal("0")]


# --- reconciliation --------------------------------------------------------

def positions(*amounts, account=ACCOUNT):
    return {"Data": [{"PositionBase": {"AccountId": account, "Uic": SOFI, "Amount": a}}
                     for a in amounts]}


def two_book_db(tmp_path):
    db = sim_db(tmp_path)
    authorize(db)
    authorize(db, order_key="sofi-2", strategy="ai-trading", broker_order_id="broker-2")
    pipeline = SaxoExecutionPipeline(db)
    pipeline.apply_buy_fill(execution(), order_key="sofi-1", account_id=ACCOUNT, now=AT)
    pipeline.apply_buy_fill(execution(execution_id="fill-2", order_id="broker-2", order_key="sofi-2"),
                            order_key="sofi-2", account_id=ACCOUNT, now=AT)
    return db, SimJournalStore(db)


def spent(store):
    ledger = store.load_ledger()
    return sum((ledger.replay(b).allocation_eur - ledger.replay(b).cash_eur for b in (TA, AI)),
               Decimal("0"))


def test_matching_evidence_is_matched_and_changes_nothing(tmp_path):
    db, store = two_book_db(tmp_path)
    before = journal_count(db)
    report = reconcile_sim_account(store.load_ledger(), SimBrokerEvidence(
        ACCOUNT, positions(1, 1), {"sofi-1": Decimal("1"), "sofi-2": Decimal("1")},
        cash_change_eur=-spent(store)), checked_at=AT + timedelta(minutes=5))
    assert (report.status, report.freeze_scope, report.frozen_books) == ("MATCHED", "NONE", ())
    apply_reconciliation(store, report)
    assert journal_count(db) == before
    assert {s.status for s in store.statuses().values()} == {"OPEN"}


def test_proven_book_specific_mismatch_freezes_only_that_book(tmp_path):
    db, store = two_book_db(tmp_path)
    before = journal_count(db)
    report = reconcile_sim_account(store.load_ledger(), SimBrokerEvidence(
        ACCOUNT, positions(3), {"sofi-1": Decimal("2"), "sofi-2": Decimal("1")}),
        checked_at=AT + timedelta(minutes=5))
    assert (report.status, report.freeze_scope, report.frozen_books) == (
        "BOOK_MISMATCH", "BOOK", (TA,))
    assert report.book_results == {TA: "MISMATCH", AI: "VERIFIED"}
    apply_reconciliation(store, report)
    statuses = store.statuses()
    assert statuses[TA].status == "FROZEN" and statuses[AI].status == "OPEN"
    assert journal_count(db) == before                       # no balancing entry anywhere
    assert store.load_ledger().replay(UNATTRIBUTED_BOOK).positions == {}
    with pytest.raises(SimAccountingError, match="book is frozen"):
        store.require_tradable(TA)
    store.require_tradable(AI)


@pytest.mark.parametrize("evidence, why", [
    (SimBrokerEvidence(ACCOUNT, positions(3), {"sofi-1": Decimal("2")}), "other book unverified"),
    (SimBrokerEvidence(ACCOUNT, positions(5), {"sofi-1": Decimal("2"), "sofi-2": Decimal("1")}),
     "difference not explained by the book"),
    (SimBrokerEvidence(ACCOUNT, positions(3), {"sofi-1": Decimal("2"), "sofi-2": Decimal("1")},
                       cash_change_eur=Decimal("-500")), "cash also wrong"),
])
def test_book_mismatch_escalates_to_account_freeze_unless_proven(tmp_path, evidence, why):
    _, store = two_book_db(tmp_path)
    report = reconcile_sim_account(store.load_ledger(), evidence, checked_at=AT + timedelta(minutes=5))
    assert (report.status, report.freeze_scope, report.frozen_books) == (
        "ACCOUNT_MISMATCH", "ACCOUNT", SIM_BOOKS), why


def test_unexplained_or_incomplete_evidence_freezes_all_sim_trading(tmp_path):
    db, store = two_book_db(tmp_path)
    unexplained = reconcile_sim_account(store.load_ledger(), SimBrokerEvidence(
        ACCOUNT, positions(1, 1, 4), {"sofi-1": Decimal("1"), "sofi-2": Decimal("1")}),
        checked_at=AT + timedelta(minutes=5))
    assert (unexplained.status, unexplained.freeze_scope) == ("ACCOUNT_MISMATCH", "ACCOUNT")
    incomplete = reconcile_sim_account(store.load_ledger(), SimBrokerEvidence(
        ACCOUNT, positions(1, 1)), checked_at=AT + timedelta(minutes=5))
    assert (incomplete.status, incomplete.freeze_scope) == ("INCOMPLETE", "ACCOUNT")
    apply_reconciliation(store, unexplained)
    assert {s.freeze_scope for s in store.statuses().values()} == {"ACCOUNT"}
    with pytest.raises(SimAccountingError, match="account-wide"):
        store.require_tradable(AI)
    assert store.load_ledger().replay(UNATTRIBUTED_BOOK).positions == {}   # nothing concealed
    assert store.last_reconciliation()["status"] == "ACCOUNT_MISMATCH"


def test_broker_positions_must_be_complete_and_for_the_sim_account(tmp_path):
    _, store = two_book_db(tmp_path)
    for bad in ({"Data": [], "__next": "/more"}, positions(1, 1, account="someone-else"), {"x": 1}):
        with pytest.raises(SimAccountingError):
            reconcile_sim_account(store.load_ledger(), SimBrokerEvidence(ACCOUNT, bad, {}),
                                  checked_at=AT)


def test_preexisting_exposure_is_a_baseline_not_strategy_capital(tmp_path):
    db, store = two_book_db(tmp_path)
    totals = {"sofi-1": Decimal("1"), "sofi-2": Decimal("1")}
    without = reconcile_sim_account(store.load_ledger(), SimBrokerEvidence(
        ACCOUNT, positions(5, 1, 1), totals), checked_at=AT)
    assert without.status == "ACCOUNT_MISMATCH"
    assert store.record_baseline(instrument_id="US:SOFI", uic=SOFI, quantity=Decimal("5"),
                                 at=AT - timedelta(minutes=30), evidence_ref="positions-snapshot")
    assert not store.record_baseline(instrument_id="US:SOFI", uic=SOFI, quantity=Decimal("5"),
                                     at=AT - timedelta(minutes=30), evidence_ref="positions-snapshot")
    ledger = store.load_ledger()
    assert ledger.replay(UNATTRIBUTED_BOOK).positions["US:SOFI"].quantity == Decimal("5")
    assert ledger.replay(TA).positions["US:SOFI"].quantity == Decimal("1")
    matched = reconcile_sim_account(ledger, SimBrokerEvidence(ACCOUNT, positions(5, 1, 1), totals),
                                    checked_at=AT)
    assert matched.status == "MATCHED"


def test_freeze_release_needs_a_later_matched_run_and_a_named_principal(tmp_path):
    _, store = two_book_db(tmp_path)
    totals = {"sofi-1": Decimal("1"), "sofi-2": Decimal("1")}
    stale_match = reconcile_sim_account(store.load_ledger(), SimBrokerEvidence(
        ACCOUNT, positions(1, 1), totals), checked_at=AT + timedelta(minutes=1))
    apply_reconciliation(store, reconcile_sim_account(store.load_ledger(), SimBrokerEvidence(
        ACCOUNT, positions(9), totals), checked_at=AT + timedelta(minutes=2)))
    with pytest.raises(SimAccountingError, match="after the freeze"):
        release_freeze(store, stale_match, released_by="operator")
    mismatch = reconcile_sim_account(store.load_ledger(), SimBrokerEvidence(
        ACCOUNT, positions(9), totals), checked_at=AT + timedelta(minutes=3))
    with pytest.raises(SimAccountingError, match="fully matched"):
        release_freeze(store, mismatch, released_by="operator")
    fresh = reconcile_sim_account(store.load_ledger(), SimBrokerEvidence(
        ACCOUNT, positions(1, 1), totals), checked_at=AT + timedelta(minutes=4))
    with pytest.raises(SimAccountingError, match="named principal"):
        release_freeze(store, fresh, released_by="bad principal; x")
    from dataclasses import replace
    from sidedeck.application.saxo_sim_reconciliation import SimReconciliationReport
    hand_built = SimReconciliationReport("MATCHED", "NONE", (), AT + timedelta(minutes=9))
    for forged in (hand_built, replace(fresh, checked_at=AT + timedelta(minutes=9))):
        with pytest.raises(SimAccountingError, match="not produced by reconcile_sim_account"):
            release_freeze(store, forged, released_by="operator")
    assert set(release_freeze(store, fresh, released_by="operator")) == set(SIM_BOOKS)
    store.require_tradable(TA)


# --- reporting -------------------------------------------------------------

def test_report_is_per_strategy_sim_only_and_never_combined(tmp_path):
    _, store = two_book_db(tmp_path)
    store.freeze((TA,), scope="BOOK", reason="proven mismatch", at=AT)
    report = sim_performance_report(store, as_of=AT, marks_usd={"US:SOFI": Decimal("44")},
                                    fx_usd_per_eur=Decimal("1.10"))
    assert report["venue"] == "SAXO_SIM" and "Never combined" in report["separation"]
    books = {b["strategy_id"]: b for b in report["strategy_books"]}
    ta = books["tradingagents"]
    assert ta["allocation_eur"] == "1000.00" and ta["cash_eur"] == "963.54"
    assert ta["fees_eur"] == "0.10" and ta["realized_pnl_eur"] == "0.00"
    assert ta["unrealized_pnl_eur"] == "3.64"            # 44/1.10 - 36.3636
    assert ta["equity_eur"] == "1003.54" and ta["return_pct"] == "0.35"
    assert ta["book_status"] == "FROZEN" and books["ai-trading"]["book_status"] == "OPEN"

    def keys(value):
        if isinstance(value, dict):
            for key, item in value.items():
                yield key
                yield from keys(item)
        elif isinstance(value, list):
            for item in value:
                yield from keys(item)

    assert not any("total" in key or "combined" in key for key in keys(report))


def test_report_without_marks_does_not_estimate(tmp_path):
    _, store = two_book_db(tmp_path)
    report = sim_performance_report(store, as_of=AT)
    ta = report["strategy_books"][0]
    assert report["marks"] == "UNAVAILABLE"
    assert ta["unrealized_pnl_eur"] is None and ta["equity_eur"] is None and ta["return_pct"] is None
