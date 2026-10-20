"""SIM books, reconciliation freezing and separate reporting (ADR-003, owner decisions 2026-10-20).

Reconciliation tests use sealed evidence collected by the real read-only
collector against a synthetic Saxo SIM gateway (no network). The adversarial
section shows that caller-built evidence, substitute ledgers, stale or
replayed evidence, other accounts and mid-transaction crashes cannot open,
reconcile or release anything.
"""
import inspect
import shutil
import sqlite3
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from sidedeck.application.saxo_execution_pipeline import SaxoExecutionPipeline
from sidedeck.application.saxo_sim_evidence import SOURCE, SimAccountEvidence, SimEvidenceError
from sidedeck.application.saxo_sim_reconciliation import (
    SimBrokerEvidence, SimReconciliationReport, compare_sim_books, open_sim_books,
    reconcile_sim_account, release_freeze, release_material,
)
from sidedeck.application.saxo_sim_report import sim_performance_report
from sidedeck.domain.sim_accounting import (
    SIM_BOOKS, UNATTRIBUTED_BOOK, SettlementSource, SimAccountingError, SimEvent, SimEventType,
    SimLedger,
)
from sidedeck.infrastructure.saxo_operator_approval import SshSignatureApprovalVerifier
from sidedeck.infrastructure.saxo_sim_journal import SimJournalStore
from sim_gateway_fake import (
    ACCOUNT, SOFI, SyntheticGateway, clock, fill_row, read_evidence, reconcile,
)
from sim_gateway_fake import open_books as open_verified_books
from test_saxo_execution_pipeline import AI, AT, TA, authorize, execution, journal_count, sim_db

OPENED = AT - timedelta(hours=1)
R1, R2, R3 = (AT + timedelta(minutes=m) for m in (5, 10, 15))
SPENT_PER_BOOK = Decimal("36.4636")              # 40 USD / 1.10 + EUR 0.10 fee
CASH_AFTER = Decimal("10000") - 2 * SPENT_PER_BOOK
SSH_KEYGEN = shutil.which("ssh-keygen")
needs_ssh = pytest.mark.skipif(SSH_KEYGEN is None, reason="ssh-keygen unavailable")


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


def broker(positions=((SOFI, 1), (SOFI, 1)), fills=(("sofi-1", 1), ("sofi-2", 1)),
           cash=CASH_AFTER, **kwargs):
    return SyntheticGateway(positions=list(positions), cash=float(cash),
                            activity=[fill_row(key, amount) for key, amount in fills], **kwargs)


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


# --- opening from verified evidence -------------------------------------------

def test_store_opens_three_books_once_for_one_verified_account(tmp_path):
    db = sim_db(tmp_path)
    store = SimJournalStore(db)
    again = read_evidence(SyntheticGateway(), OPENED + timedelta(minutes=1))
    with clock(OPENED + timedelta(minutes=1)):
        assert not open_sim_books(store, again, approval_ref="owner")
    other = read_evidence(SyntheticGateway("another"), OPENED + timedelta(minutes=2))
    with clock(OPENED + timedelta(minutes=2)), pytest.raises(SimAccountingError,
                                                             match="different account"):
        open_sim_books(store, other, approval_ref="owner")
    statuses = store.statuses()
    assert set(statuses) == set(SIM_BOOKS) and {s.status for s in statuses.values()} == {"OPEN"}
    ledger = store.load_ledger()
    assert [ledger.replay(b).allocation_eur for b in (TA, AI, UNATTRIBUTED_BOOK)] == [
        Decimal("1000"), Decimal("1000"), Decimal("0")]
    opening = store.opening()
    assert opening is not None and opening.account_id == ACCOUNT
    assert opening.cash_balance_eur == Decimal("10000")
    assert opening.source == SOURCE and opening.observed_at == OPENED


def test_store_has_no_unverified_open_baseline_freeze_or_release_path(tmp_path):
    store = SimJournalStore(str(tmp_path / "s.sqlite"))
    for name in ("open_books", "record_baseline", "freeze", "release"):
        assert not hasattr(store, name), name
    with store.transaction() as db:
        db.execute("COMMIT")          # primitives refuse to run outside a transaction
        with pytest.raises(SimAccountingError, match="IMMEDIATE"):
            store._freeze(db, (TA,), scope="BOOK", reason="x", at=AT)
        db.execute("BEGIN IMMEDIATE")


def test_opening_needs_sealed_fresh_evidence(tmp_path):
    store = SimJournalStore(str(tmp_path / "open.sqlite"))
    genuine = read_evidence(SyntheticGateway(), OPENED)
    hand_built = SimAccountEvidence(genuine.evidence_id, SOURCE, ACCOUNT, genuine.scope_sha256,
                                    OPENED, (), Decimal("10000"), (), genuine.response_sha256,
                                    seal="forged")
    tampered = replace(genuine, cash_balance_eur=Decimal("999999"))     # keeps the old seal
    with clock(OPENED):
        for bad in (hand_built, tampered, None):
            with pytest.raises(SimEvidenceError, match="read-only SIM gateway"):
                open_sim_books(store, bad, approval_ref="owner")   # type: ignore[arg-type]
    with clock(OPENED + timedelta(minutes=6)), pytest.raises(SimEvidenceError, match="stale"):
        open_sim_books(store, genuine, approval_ref="owner")
    assert store.statuses() == {} and store.opening() is None


def test_preexisting_exposure_is_a_verified_baseline_not_strategy_capital(tmp_path):
    db = str(tmp_path / "baseline.sqlite")
    store = open_verified_books(db, OPENED, SyntheticGateway(positions=[(SOFI, 5)]))
    ledger = store.load_ledger()
    assert ledger.replay(UNATTRIBUTED_BOOK).positions["US:SOFI"].quantity == Decimal("5")
    assert ledger.replay(UNATTRIBUTED_BOOK).allocation_eur == 0
    opening = store.opening()
    assert ledger.replay(TA).positions == {} and opening is not None
    assert opening.positions == {SOFI: Decimal("5")}
    authorize(db)
    authorize(db, order_key="sofi-2", strategy="ai-trading", broker_order_id="broker-2")
    pipeline = SaxoExecutionPipeline(db)
    pipeline.apply_buy_fill(execution(), order_key="sofi-1", account_id=ACCOUNT, now=AT)
    pipeline.apply_buy_fill(execution(execution_id="fill-2", order_id="broker-2", order_key="sofi-2"),
                            order_key="sofi-2", account_id=ACCOUNT, now=AT)
    report = reconcile(store, broker(positions=[(SOFI, 5), (SOFI, 1), (SOFI, 1)]), R1)
    assert report.status == "MATCHED"


# --- reconciliation decisions -----------------------------------------------

def two_book_db(tmp_path):
    db = sim_db(tmp_path)
    authorize(db)
    authorize(db, order_key="sofi-2", strategy="ai-trading", broker_order_id="broker-2")
    pipeline = SaxoExecutionPipeline(db)
    pipeline.apply_buy_fill(execution(), order_key="sofi-1", account_id=ACCOUNT, now=AT)
    pipeline.apply_buy_fill(execution(execution_id="fill-2", order_id="broker-2", order_key="sofi-2"),
                            order_key="sofi-2", account_id=ACCOUNT, now=AT)
    return db, SimJournalStore(db)


def runs(db):
    with sqlite3.connect(db) as connection:
        return connection.execute("SELECT status, evidence_id, journal_sha256 "
                                  "FROM saxo_sim_reconciliation_runs ORDER BY run_id").fetchall()


def test_matching_evidence_is_matched_bound_and_changes_nothing(tmp_path):
    db, store = two_book_db(tmp_path)
    before = journal_count(db)
    report = reconcile(store, broker(), R1)
    assert (report.status, report.freeze_scope, report.frozen_books) == ("MATCHED", "NONE", ())
    assert report.is_genuine() and report.account_id == ACCOUNT and report.observed_at == R1
    assert journal_count(db) == before
    assert {s.status for s in store.statuses().values()} == {"OPEN"}
    assert runs(db) == [("MATCHED", report.report_id, report.journal_sha256)]


def test_proven_book_specific_mismatch_freezes_only_that_book(tmp_path):
    db, store = two_book_db(tmp_path)
    before = journal_count(db)
    report = reconcile(store, broker(positions=[(SOFI, 3)], fills=[("sofi-1", 2), ("sofi-2", 1)]), R1)
    assert (report.status, report.freeze_scope, report.frozen_books) == ("BOOK_MISMATCH", "BOOK", (TA,))
    assert report.book_results == {TA: "MISMATCH", AI: "VERIFIED"}
    statuses = store.statuses()
    assert statuses[TA].status == "FROZEN" and statuses[AI].status == "OPEN"
    assert journal_count(db) == before                       # no balancing entry anywhere
    assert store.load_ledger().replay(UNATTRIBUTED_BOOK).positions == {}
    with pytest.raises(SimAccountingError, match="book is frozen"):
        store.require_tradable(TA)
    store.require_tradable(AI)


@pytest.mark.parametrize("gateway, why", [
    (broker(positions=[(SOFI, 3)], fills=[("sofi-1", 2)]), "other book unverified"),
    (broker(positions=[(SOFI, 5)], fills=[("sofi-1", 2), ("sofi-2", 1)]),
     "difference not explained by the book"),
    (broker(positions=[(SOFI, 3)], fills=[("sofi-1", 2), ("sofi-2", 1)], cash=CASH_AFTER - 40),
     "cash also wrong"),
])
def test_book_mismatch_escalates_to_account_freeze_unless_proven(tmp_path, gateway, why):
    _, store = two_book_db(tmp_path)
    report = reconcile(store, gateway, R1)
    assert (report.status, report.freeze_scope, report.frozen_books) == (
        "ACCOUNT_MISMATCH", "ACCOUNT", SIM_BOOKS), why


def test_unexplained_position_freezes_all_sim_trading(tmp_path):
    _, store = two_book_db(tmp_path)
    report = reconcile(store, broker(positions=[(SOFI, 1), (SOFI, 1), (SOFI, 4)]), R1)
    assert (report.status, report.freeze_scope) == ("ACCOUNT_MISMATCH", "ACCOUNT")
    assert {s.freeze_scope for s in store.statuses().values()} == {"ACCOUNT"}
    with pytest.raises(SimAccountingError, match="account-wide"):
        store.require_tradable(AI)
    assert store.load_ledger().replay(UNATTRIBUTED_BOOK).positions == {}   # nothing concealed
    last = store.last_reconciliation()
    assert last is not None and last["status"] == "ACCOUNT_MISMATCH"


def test_missing_cash_evidence_is_incomplete_never_matched(tmp_path):
    db, store = two_book_db(tmp_path)
    decision = compare_sim_books(store.load_ledger(), SimBrokerEvidence(
        ACCOUNT, {SOFI: Decimal("2")}, {"sofi-1": Decimal("1"), "sofi-2": Decimal("1")}, None))
    assert (decision.status, decision.freeze_scope, decision.frozen_books) == (
        "INCOMPLETE", "ACCOUNT", SIM_BOOKS)
    assert "account: broker cash evidence missing" in decision.discrepancies
    proven_book = compare_sim_books(store.load_ledger(), SimBrokerEvidence(
        ACCOUNT, {SOFI: Decimal("3")}, {"sofi-1": Decimal("2"), "sofi-2": Decimal("1")}, None))
    assert proven_book.freeze_scope == "ACCOUNT"     # no cash -> not proven book-specific
    for balance in ({"Currency": "USD", "CashBalance": 10000}, {"Currency": "EUR"},
                    {"Currency": "EUR", "CashBalance": True}):
        gateway = broker()
        gateway.balance_response = balance
        with pytest.raises(SimEvidenceError):
            read_evidence(gateway, R1)
    assert runs(db) == []


def test_unjournaled_broker_fill_for_an_approved_order_is_caught(tmp_path):
    db, store = two_book_db(tmp_path)
    authorize(db, order_key="sofi-3", strategy="ai-trading", broker_order_id="broker-3")
    assert reconcile(store, broker(), R1).status == "MATCHED"    # approved, never filled
    report = reconcile(store, broker(positions=[(SOFI, 3)],
                                     fills=[("sofi-1", 1), ("sofi-2", 1), ("sofi-3", 1)]), R2)
    assert (report.status, report.frozen_books) == ("BOOK_MISMATCH", (AI,))
    assert report.book_results == {TA: "VERIFIED", AI: "MISMATCH"}


@pytest.mark.parametrize("mutate", [
    lambda g: setattr(g, "positions_response", {"Data": [], "__next": "/more"}),
    lambda g: setattr(g, "positions_response", {"Data": [], "__count": 3}),
    lambda g: setattr(g, "positions_response", {"Data": [{"PositionBase": {
        "AccountId": "someone-else", "Uic": SOFI, "Amount": 1}}]}),
    lambda g: g.activity.append(fill_row("sofi-9", 1, account_id="someone-else")),
    lambda g: g.activity.append(dict(g.activity[0])),                    # duplicate execution
    lambda g: g.activity.append(fill_row("sofi-9", 1, side="Sell")),
    lambda g: g.activity.append(fill_row("sofi-9", "NaN")),
])
def test_broker_evidence_must_be_complete_and_for_the_sim_account(mutate):
    gateway = broker()
    mutate(gateway)
    with pytest.raises(SimEvidenceError):
        read_evidence(gateway, R1)


def test_freeze_scope_is_never_downgraded(tmp_path):
    _, store = two_book_db(tmp_path)
    reconcile(store, broker(positions=[(SOFI, 9)]), R1)
    reconcile(store, broker(positions=[(SOFI, 3)], fills=[("sofi-1", 2), ("sofi-2", 1)]), R2)
    assert {s.freeze_scope for s in store.statuses().values()} == {"ACCOUNT"}
    with pytest.raises(SimAccountingError, match="account-wide"):
        store.require_tradable(AI)


# --- adversarial: trust boundary ----------------------------------------------

def test_hand_built_or_tampered_evidence_cannot_reconcile(tmp_path):
    db, store = two_book_db(tmp_path)
    genuine = read_evidence(broker(positions=[(SOFI, 9)]), R1)
    clean_positions = ((SOFI, Decimal("2")),)
    clean_fills = (("sofi-1", Decimal("1")), ("sofi-2", Decimal("1")))
    forgeries = [
        replace(genuine, positions=clean_positions, order_fill_totals=clean_fills,
                cash_balance_eur=CASH_AFTER),                               # old seal, new values
        SimAccountEvidence("x", SOURCE, ACCOUNT, genuine.scope_sha256, R1, clean_positions,
                           CASH_AFTER, clean_fills, "0" * 64, seal="0" * 64),
        replace(genuine, source="caller-fixture"),
        SimBrokerEvidence(ACCOUNT, {SOFI: Decimal("2")}, {}, Decimal("0")),
    ]
    with clock(R1):
        for forged in forgeries:
            with pytest.raises(SimEvidenceError, match="read-only SIM gateway"):
                reconcile_sim_account(store, forged)   # type: ignore[arg-type]
    assert runs(db) == [] and {s.status for s in store.statuses().values()} == {"OPEN"}


def test_reconciliation_uses_the_persisted_journal_not_a_caller_ledger(tmp_path):
    assert "ledger" not in inspect.signature(reconcile_sim_account).parameters
    _, store = two_book_db(tmp_path)
    # Broker evidence that an empty substitute ledger would have "matched":
    report = reconcile(store, SyntheticGateway(cash=10000), R1)
    assert report.status != "MATCHED" and report.freeze_scope == "ACCOUNT"
    unopened = SimJournalStore(str(tmp_path / "unopened.sqlite"))
    evidence = read_evidence(SyntheticGateway(), R2)
    with clock(R2), pytest.raises(SimAccountingError, match="not opened from verified evidence"):
        reconcile_sim_account(unopened, evidence)


def test_stale_replayed_or_out_of_order_evidence_is_refused(tmp_path):
    db, store = two_book_db(tmp_path)
    late = read_evidence(broker(), R1)
    with clock(R1 + timedelta(minutes=6)), pytest.raises(SimEvidenceError, match="stale"):
        reconcile_sim_account(store, late)
    older = read_evidence(broker(), R1)
    newer = read_evidence(broker(), R1 + timedelta(minutes=1))
    with clock(R1 + timedelta(minutes=2)):
        assert reconcile_sim_account(store, newer).status == "MATCHED"
        for replayed in (newer, older):
            with pytest.raises(SimEvidenceError, match="not newer"):
                reconcile_sim_account(store, replayed)
    assert [row[0] for row in runs(db)] == ["MATCHED"]
    fresh = SimJournalStore(sim_db(tmp_path, "fresh.sqlite"))
    before_opening = read_evidence(SyntheticGateway(), OPENED - timedelta(minutes=1))
    with clock(OPENED), pytest.raises(SimEvidenceError, match="predates"):
        reconcile_sim_account(fresh, before_opening)


@pytest.mark.parametrize("account_id, keys", [
    ("another-account", {}),
    (ACCOUNT, {"client_key": "different-client"}),
    (ACCOUNT, {"account_key": "different-account-key"}),
])
def test_evidence_from_another_account_or_login_is_refused(tmp_path, account_id, keys):
    db, store = two_book_db(tmp_path)
    gateway = SyntheticGateway(account_id, positions=[(SOFI, 1), (SOFI, 1)], cash=float(CASH_AFTER),
                               activity=[fill_row("sofi-1", 1, account_id=account_id),
                                         fill_row("sofi-2", 1, account_id=account_id)], **keys)
    with pytest.raises(SimEvidenceError, match="different Saxo account"):
        reconcile(store, gateway, R1)
    assert runs(db) == []


@pytest.mark.parametrize("crash_point", ["_record_run", "_freeze", "after_freeze"])
def test_crash_during_reconciliation_leaves_no_partial_decision(tmp_path, monkeypatch, crash_point):
    db, store = two_book_db(tmp_path)
    evidence = read_evidence(broker(positions=[(SOFI, 9)]), R1)
    target = "_freeze" if crash_point == "after_freeze" else crash_point
    original = getattr(SimJournalStore, target)

    def crash(self, *args, **kwargs):
        if crash_point == "after_freeze":
            original(self, *args, **kwargs)      # the freeze is written, then the process dies
        raise KeyboardInterrupt("simulated crash")

    monkeypatch.setattr(SimJournalStore, target, crash)
    with clock(R1), pytest.raises(KeyboardInterrupt):
        reconcile_sim_account(store, evidence)
    # Nothing half-done: no recorded decision and no partial freeze.
    assert runs(db) == [] and {s.status for s in store.statuses().values()} == {"OPEN"}
    monkeypatch.undo()
    with clock(R1 + timedelta(minutes=1)):
        report = reconcile_sim_account(store, evidence)   # same evidence, still fresh, not consumed
    assert report.freeze_scope == "ACCOUNT"
    assert [row[0] for row in runs(db)] == ["ACCOUNT_MISMATCH"]
    assert {s.status for s in store.statuses().values()} == {"FROZEN"}


# --- signed freeze release -------------------------------------------------------

def operator(tmp_path):
    from test_saxo_operator_approval import operator_setup, operator_signs
    key, signers = operator_setup(tmp_path)
    verifier = SshSignatureApprovalVerifier(signers, ssh_keygen=SSH_KEYGEN)
    count = iter(range(1000))

    def sign(material):
        work = tmp_path / f"signature-{next(count)}"      # ssh-keygen never overwrites a .sig
        work.mkdir()
        return operator_signs(work, key, material)

    return verifier, sign


class AlwaysYes:
    def verify(self, attestation, material, principal):
        return True


@needs_ssh
def test_release_needs_a_fresh_latest_matched_run_and_an_operator_signature(tmp_path):
    db, store = two_book_db(tmp_path)
    verifier, sign = operator(tmp_path)
    frozen = reconcile(store, broker(positions=[(SOFI, 9)]), R1)
    assert frozen.freeze_scope == "ACCOUNT"
    with clock(R1), pytest.raises(SimAccountingError, match="fully matched"):
        release_freeze(store, frozen, released_by="operator",
                       attestation=sign(release_material(frozen, released_by="operator")),
                       verifier=verifier)
    first = reconcile(store, broker(), R2)
    latest = reconcile(store, broker(), R3)
    good = sign(release_material(latest, released_by="operator"))
    hand_built = SimReconciliationReport(latest.report_id, ACCOUNT, "MATCHED", "NONE", (), R3, R3,
                                         latest.journal_sha256, latest.evidence_sha256)
    with clock(R3):
        for forged in (hand_built, replace(latest, observed_at=R3 + timedelta(minutes=1))):
            with pytest.raises(SimAccountingError, match="not produced by reconcile_sim_account"):
                release_freeze(store, forged, released_by="operator", attestation=good,
                               verifier=verifier)
        with pytest.raises(SimAccountingError, match="named principal"):
            release_freeze(store, latest, released_by="bad principal; x", attestation=good,
                           verifier=verifier)
        with pytest.raises(SimAccountingError, match="signature verifier"):
            release_freeze(store, latest, released_by="operator", attestation=good,
                           verifier=AlwaysYes())   # type: ignore[arg-type]
        for attestation, principal in (
                (sign(release_material(first, released_by="operator")), "operator"),  # other report
                (good, "someone-else"),                                               # not the signer
                ("-----BEGIN SSH SIGNATURE-----\nAAAA\n-----END SSH SIGNATURE-----", "operator")):
            with pytest.raises(SimAccountingError, match="does not verify"):
                release_freeze(store, latest, released_by=principal, attestation=attestation,
                               verifier=verifier)
        with pytest.raises(SimAccountingError, match="latest recorded"):
            release_freeze(store, first, released_by="operator",
                           attestation=sign(release_material(first, released_by="operator")),
                           verifier=verifier)
    with clock(R3 + timedelta(minutes=6)), pytest.raises(SimEvidenceError, match="stale"):
        release_freeze(store, latest, released_by="operator", attestation=good, verifier=verifier)
    assert {s.status for s in store.statuses().values()} == {"FROZEN"}
    with clock(R3 + timedelta(minutes=1)):
        assert set(release_freeze(store, latest, released_by="operator", attestation=good,
                                  verifier=verifier)) == set(SIM_BOOKS)
    store.require_tradable(TA)
    with sqlite3.connect(db) as connection:
        audit = connection.execute("SELECT released_by, report_id FROM saxo_sim_freeze_releases"
                                   ).fetchall()
    assert audit == [("operator", latest.report_id)]


@needs_ssh
def test_release_refuses_evidence_read_before_the_freeze(tmp_path):
    _, store = two_book_db(tmp_path)
    verifier, sign = operator(tmp_path)
    freezing = read_evidence(broker(positions=[(SOFI, 9)]), R1)
    clean_but_earlier = read_evidence(broker(), R1 + timedelta(seconds=20))
    with clock(R1 + timedelta(seconds=40)):
        reconcile_sim_account(store, freezing)               # frozen_at = R1 + 40s
    with clock(R1 + timedelta(seconds=50)):
        report = reconcile_sim_account(store, clean_but_earlier)
        assert report.status == "MATCHED"
        with pytest.raises(SimAccountingError, match="after the freeze"):
            release_freeze(store, report, released_by="operator",
                           attestation=sign(release_material(report, released_by="operator")),
                           verifier=verifier)


@needs_ssh
def test_release_refuses_when_the_journal_changed_after_reconciliation(tmp_path):
    db, store = two_book_db(tmp_path)
    verifier, sign = operator(tmp_path)
    reconcile(store, broker(positions=[(SOFI, 3)], fills=[("sofi-1", 2), ("sofi-2", 1)]), R1)
    assert store.statuses()[TA].status == "FROZEN" and store.statuses()[AI].status == "OPEN"
    report = reconcile(store, broker(), R2)
    assert report.status == "MATCHED"
    authorize(db, order_key="sofi-3", strategy="ai-trading", broker_order_id="broker-3")
    SaxoExecutionPipeline(db).apply_buy_fill(
        execution(execution_id="fill-3", order_id="broker-3", order_key="sofi-3"),
        order_key="sofi-3", account_id=ACCOUNT, now=AT)       # AI is still tradable
    with clock(R2), pytest.raises(SimAccountingError, match="journal changed"):
        release_freeze(store, report, released_by="operator",
                       attestation=sign(release_material(report, released_by="operator")),
                       verifier=verifier)
    assert store.statuses()[TA].status == "FROZEN"


# --- reporting -------------------------------------------------------------

def test_report_is_per_strategy_sim_only_and_never_combined(tmp_path):
    _, store = two_book_db(tmp_path)
    with store.transaction() as db:
        store._freeze(db, (TA,), scope="BOOK", reason="proven mismatch", at=AT)
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
