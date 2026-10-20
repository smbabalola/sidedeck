"""Read-only Saxo SIM reconciliation with fail-closed freezing (ADR-003 §4).

Trust boundary (P4 review follow-up, 2026-10-20):

* Only ``SimAccountEvidence`` sealed by ``collect_account_evidence`` (GET-only,
  verified account scope, SIM gateway client) can open books, record a
  reconciliation or lead to a freeze release. Caller-built evidence, a
  substitute ledger or a replayed report cannot.
* ``reconcile_sim_account`` loads the persisted journal itself, compares it,
  records the run and applies any freeze in ONE IMMEDIATE transaction. A crash
  leaves either the complete decision or nothing.
* ``release_freeze`` needs a sealed MATCHED report that is still the latest
  recorded run, an unchanged journal, evidence read after the freeze and still
  fresh, and an OpenSSH signature from an operator in ``allowed_signers``.

Freeze policy (owner decision, 2026-10-20):
- unexplained, account-wide or incomplete evidence (including missing cash)
  -> freeze ALL SIM books;
- a proven book-specific mismatch freezes only that book, and only when every
  other strategy book is independently verified against broker order evidence,
  the account position difference is fully explained by it and cash agrees.

Nothing here contacts a broker, posts journal entries, or touches research
ledgers or Alpaca paper accounts. Discrepancies are never "balanced" into any
book, including the unattributed control book.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal

from sidedeck.application import saxo_sim_evidence as sim_evidence
from sidedeck.application.saxo_sim_evidence import (
    INSTRUMENT_IDS, MAX_EVIDENCE_AGE, SimAccountEvidence, SimEvidenceError, parse_positions,
    require_verified,
)
from sidedeck.domain.sim_accounting import (
    SIM_BOOKS, STRATEGY_BOOKS, SimAccountingError, SimEventType, SimLedger,
)
from sidedeck.infrastructure.saxo_operator_approval import (
    APPROVAL_NAMESPACE, SshSignatureApprovalVerifier, valid_principal,
)
from sidedeck.infrastructure.saxo_sim_journal import SimJournalStore

__all__ = [
    "RELEASE_PURPOSE", "ReconciliationDecision", "SimBrokerEvidence", "SimReconciliationReport",
    "compare_sim_books", "open_sim_books", "parse_positions", "reconcile_sim_account",
    "release_freeze", "release_material",
]

ZERO = Decimal("0")
CASH_TOLERANCE_EUR = Decimal("1.00")
RELEASE_PURPOSE = "saxo-sim-freeze-release"
# Process-local key: only reconcile_sim_account() can produce a report that
# release_freeze() will accept; a hand-built "MATCHED" report cannot unfreeze.
_REPORT_SEAL_KEY = secrets.token_bytes(32)


@dataclass(frozen=True)
class SimBrokerEvidence:
    """Plain comparison input. It cannot open, freeze or release anything."""

    account_id: str
    positions: Mapping[int, Decimal]
    order_fill_totals: Mapping[str, Decimal] | None = None   # order_key -> broker FillAmount total
    cash_change_eur: Decimal | None = None                   # broker cash change since books opened


@dataclass(frozen=True)
class ReconciliationDecision:
    status: str            # MATCHED | BOOK_MISMATCH | ACCOUNT_MISMATCH | INCOMPLETE
    freeze_scope: str      # NONE | BOOK | ACCOUNT
    frozen_books: tuple[str, ...]
    book_results: dict[str, str]   # VERIFIED | MISMATCH | UNVERIFIED
    discrepancies: tuple[str, ...]


@dataclass(frozen=True)
class SimReconciliationReport:
    report_id: str         # the evidence ID; each piece of evidence reconciles once
    account_id: str
    status: str
    freeze_scope: str
    frozen_books: tuple[str, ...]
    checked_at: datetime
    observed_at: datetime
    journal_sha256: str
    evidence_sha256: str
    book_results: dict[str, str] = field(default_factory=dict)
    discrepancies: tuple[str, ...] = ()
    seal: str = field(default="", repr=False, compare=False)

    def _mac(self) -> str:
        material = json.dumps([
            self.report_id, self.account_id, self.status, self.freeze_scope,
            list(self.frozen_books), self.checked_at.isoformat(), self.observed_at.isoformat(),
            self.journal_sha256, self.evidence_sha256, sorted(self.book_results.items()),
            list(self.discrepancies)], separators=(",", ":"))
        return hmac.new(_REPORT_SEAL_KEY, material.encode("utf-8"), hashlib.sha256).hexdigest()

    def is_genuine(self) -> bool:
        return bool(self.seal) and hmac.compare_digest(self._mac(), self.seal)


# --- pure comparison ------------------------------------------------------------

def _internal_positions(ledger: SimLedger) -> dict[int, Decimal]:
    totals: dict[int, Decimal] = {}
    for book in SIM_BOOKS:
        for position in ledger.replay(book).positions.values():
            totals[position.uic] = totals.get(position.uic, ZERO) + position.quantity
    return totals


def _order_fills(ledger: SimLedger, book: str) -> dict[str, tuple[int, Decimal]]:
    fills: dict[str, tuple[int, Decimal]] = {}
    for event in ledger.events:
        if event.book_id == book and event.event_type is SimEventType.SIM_BUY_FILL:
            assert event.order_key and event.quantity is not None and event.uic is not None
            uic, qty = fills.get(event.order_key, (event.uic, ZERO))
            fills[event.order_key] = (uic, qty + event.quantity)
    return fills


def compare_sim_books(ledger: SimLedger, evidence: SimBrokerEvidence, *,
                      authorized_orders: Mapping[str, tuple[str, int]] | None = None,
                      cash_tolerance_eur: Decimal = CASH_TOLERANCE_EUR) -> ReconciliationDecision:
    """Compare books with broker facts; returns a decision and changes nothing.

    ``authorized_orders`` maps SideDeck order keys to (book, Uic) for every
    operator-approved order, so broker fills for an order that never reached
    the journal are attributed to its book instead of passing unseen.
    """
    discrepancies: list[str] = []
    book_results: dict[str, str] = {}
    corrections: dict[int, Decimal] = {}   # broker minus journal, per Uic, for mismatches
    for book in STRATEGY_BOOKS.values():
        result = "VERIFIED"
        orders = _order_fills(ledger, book)
        for order_key, (order_book, uic) in (authorized_orders or {}).items():
            if order_book == book and order_key not in orders:
                orders[order_key] = (uic, ZERO)
        for order_key, (uic, journal_qty) in sorted(orders.items()):
            broker_qty = (None if evidence.order_fill_totals is None
                          else evidence.order_fill_totals.get(order_key))
            if broker_qty is None and journal_qty == 0 and evidence.order_fill_totals is not None:
                continue   # approved, never filled at the broker, nothing journaled
            if broker_qty is None:
                result = "UNVERIFIED" if result == "VERIFIED" else result
                discrepancies.append(f"{book}: no broker fill evidence for {order_key}")
            elif broker_qty != journal_qty:
                result = "MISMATCH"
                corrections[uic] = corrections.get(uic, ZERO) + broker_qty - journal_qty
                discrepancies.append(f"{book}: {order_key} journal {journal_qty} vs broker {broker_qty}")
        book_results[book] = result

    internal = _internal_positions(ledger)
    broker = dict(evidence.positions)
    position_diff = {uic: broker.get(uic, ZERO) - internal.get(uic, ZERO)
                     for uic in set(broker) | set(internal)
                     if broker.get(uic, ZERO) != internal.get(uic, ZERO)}
    for uic, diff in sorted(position_diff.items()):
        discrepancies.append(f"account: Uic {uic} broker minus books = {diff}")

    cash_missing = evidence.cash_change_eur is None
    cash_mismatch = False
    if cash_missing:
        discrepancies.append("account: broker cash evidence missing")
    else:
        assert evidence.cash_change_eur is not None
        spent = sum((ledger.replay(b).allocation_eur - ledger.replay(b).cash_eur
                     for b in STRATEGY_BOOKS.values()), ZERO)
        if abs(evidence.cash_change_eur + spent) > cash_tolerance_eur:
            cash_mismatch = True
            discrepancies.append(f"account: cash change {evidence.cash_change_eur} vs books {-spent}")

    mismatched = tuple(b for b, r in book_results.items() if r == "MISMATCH")
    unverified = [b for b, r in book_results.items() if r == "UNVERIFIED"]
    if not (mismatched or unverified or position_diff or cash_mismatch or cash_missing):
        return ReconciliationDecision("MATCHED", "NONE", (), book_results, ())
    if mismatched:
        others_verified = all(book_results[b] == "VERIFIED"
                              for b in STRATEGY_BOOKS.values() if b not in mismatched)
        explained = position_diff == {u: d for u, d in corrections.items() if d != 0}
        if others_verified and explained and not cash_mismatch and not cash_missing:
            return ReconciliationDecision("BOOK_MISMATCH", "BOOK", mismatched, book_results,
                                          tuple(discrepancies))
        return ReconciliationDecision("ACCOUNT_MISMATCH", "ACCOUNT", SIM_BOOKS, book_results,
                                      tuple(discrepancies))
    if position_diff or cash_mismatch:
        return ReconciliationDecision("ACCOUNT_MISMATCH", "ACCOUNT", SIM_BOOKS, book_results,
                                      tuple(discrepancies))
    return ReconciliationDecision("INCOMPLETE", "ACCOUNT", SIM_BOOKS, book_results,
                                  tuple(discrepancies))


# --- verified, persisted operations ---------------------------------------------

def open_sim_books(store: SimJournalStore, evidence: SimAccountEvidence, *,
                   approval_ref: str) -> bool:
    """Open the three books from sealed, fresh account evidence (idempotent).

    The opening EUR cash balance and every pre-existing position come from
    that evidence; positions go to the unattributed control book as baselines.
    """
    evidence = require_verified(evidence)
    evidence.require_fresh(sim_evidence.utcnow())
    positions = evidence.positions_by_uic()
    instrument_ids = {uic: INSTRUMENT_IDS.get(uic, f"SAXO-UIC:{uic}") for uic in positions}
    with store.transaction() as db:
        return store._open_from_evidence(
            db, account_id=evidence.account_id, scope_sha256=evidence.scope_sha256,
            evidence_id=evidence.evidence_id, source=evidence.source,
            observed_at=evidence.observed_at, cash_balance_eur=evidence.cash_balance_eur,
            positions=positions, instrument_ids=instrument_ids,
            evidence_sha256=evidence.digest(), approval_ref=approval_ref)


def _authorized_orders(db: sqlite3.Connection) -> dict[str, tuple[str, int]]:
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                      "AND name='saxo_execution_authorization'").fetchone():
        return {}
    rows = db.execute("SELECT order_key, book_id FROM saxo_execution_authorization "
                      "WHERE book_id IS NOT NULL").fetchall()
    # Only SOFI orders can be prepared today (prepare_sofi_request).
    return {order_key: (book_id, sim_evidence.SOFI_UIC) for order_key, book_id in rows}


def reconcile_sim_account(store: SimJournalStore, evidence: SimAccountEvidence, *,
                          cash_tolerance_eur: Decimal = CASH_TOLERANCE_EUR) -> SimReconciliationReport:
    """Compare the persisted journal with sealed broker evidence; record and freeze atomically."""
    evidence = require_verified(evidence)
    now = sim_evidence.utcnow()
    evidence.require_fresh(now)
    with store.transaction() as db:
        opening = store.opening(db)
        if opening is None:
            raise SimAccountingError("Saxo SIM books were not opened from verified evidence")
        if (evidence.account_id, evidence.scope_sha256) != (opening.account_id, opening.scope_sha256):
            raise SimEvidenceError("broker evidence is for a different Saxo account")
        if evidence.observed_at <= opening.observed_at:
            raise SimEvidenceError("broker evidence predates the SIM books")
        latest = store.latest_run(db)
        if latest is not None and latest.observed_at and evidence.observed_at <= latest.observed_at:
            raise SimEvidenceError("broker evidence is not newer than the latest reconciliation")
        ledger = store.load(db)
        journal_sha256 = store.journal_digest(db)
        decision = compare_sim_books(
            ledger,
            SimBrokerEvidence(evidence.account_id, evidence.positions_by_uic(),
                              evidence.fill_totals(),
                              evidence.cash_balance_eur - opening.cash_balance_eur),
            authorized_orders=_authorized_orders(db), cash_tolerance_eur=cash_tolerance_eur)
        report = SimReconciliationReport(
            report_id=evidence.evidence_id, account_id=evidence.account_id,
            status=decision.status, freeze_scope=decision.freeze_scope,
            frozen_books=decision.frozen_books, checked_at=now, observed_at=evidence.observed_at,
            journal_sha256=journal_sha256, evidence_sha256=evidence.digest(),
            book_results=decision.book_results, discrepancies=decision.discrepancies)
        report = replace(report, seal=report._mac())
        store._record_run(db, checked_at=now, status=report.status, scope=report.freeze_scope,
                          frozen_books=report.frozen_books, discrepancies=report.discrepancies,
                          account_id=report.account_id, evidence_id=report.report_id,
                          source=evidence.source, observed_at=report.observed_at,
                          journal_sha256=journal_sha256, evidence_sha256=report.evidence_sha256)
        if report.freeze_scope != "NONE":
            store._freeze(db, report.frozen_books, scope=report.freeze_scope,
                          reason="; ".join(report.discrepancies)[:2000] or report.status, at=now)
    return report


def release_material(report: SimReconciliationReport, *, released_by: str) -> str:
    """Exact text the operator reviews and signs (outside SideDeck) to lift a freeze."""
    return json.dumps({
        "purpose": RELEASE_PURPOSE, "namespace": APPROVAL_NAMESPACE,
        "report_id": report.report_id, "account_id": report.account_id,
        "status": report.status, "observed_at": report.observed_at.isoformat(),
        "journal_sha256": report.journal_sha256, "evidence_sha256": report.evidence_sha256,
        "released_by": released_by,
    }, sort_keys=True, separators=(",", ":"))


def release_freeze(store: SimJournalStore, report: SimReconciliationReport, *, released_by: str,
                   attestation: str, verifier: SshSignatureApprovalVerifier) -> tuple[str, ...]:
    """Unfreeze after a later, fully MATCHED, verified run and a signed operator release."""
    if not isinstance(report, SimReconciliationReport) or not report.is_genuine():
        raise SimAccountingError("reconciliation report was not produced by reconcile_sim_account")
    if report.status != "MATCHED" or report.freeze_scope != "NONE":
        raise SimAccountingError("only a fully matched reconciliation can release a freeze")
    if not valid_principal(released_by):
        raise SimAccountingError("a named principal must release a freeze")
    if type(verifier) is not SshSignatureApprovalVerifier:
        raise SimAccountingError("release needs the operator signature verifier (allowed_signers)")
    now = sim_evidence.utcnow()
    if now - report.observed_at > MAX_EVIDENCE_AGE:
        raise SimEvidenceError("reconciliation evidence is stale; collect fresh evidence")
    if not verifier.verify(attestation, release_material(report, released_by=released_by),
                           released_by):
        raise SimAccountingError("operator signature does not verify for this release")
    with store.transaction() as db:
        latest = store.latest_run(db)
        if (latest is None or latest.status != "MATCHED" or latest.evidence_id != report.report_id
                or latest.evidence_sha256 != report.evidence_sha256
                or latest.journal_sha256 != report.journal_sha256):
            raise SimAccountingError("release must use the latest recorded reconciliation")
        if store.journal_digest(db) != report.journal_sha256:
            raise SimAccountingError("SIM journal changed since the reconciliation")
        frozen = {b: s for b, s in store.statuses(db).items() if s.status == "FROZEN"}
        for status in frozen.values():
            if status.frozen_at is None or report.observed_at <= datetime.fromisoformat(status.frozen_at):
                raise SimAccountingError("release needs a reconciliation run after the freeze")
        books = tuple(sorted(frozen))
        if books:
            store._release(db, books, released_by=released_by, report_id=report.report_id,
                           attestation_sha256=hashlib.sha256(attestation.encode("utf-8")).hexdigest(),
                           at=now)
    return books
