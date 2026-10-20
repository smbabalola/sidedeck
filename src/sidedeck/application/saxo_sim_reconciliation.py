"""Read-only Saxo SIM reconciliation with fail-closed freezing (ADR-003 §4).

Inputs are injected broker evidence (positions, per-order fill totals from
order activity, cash change). Nothing here contacts a broker, posts journal
entries, or touches research ledgers or Alpaca paper accounts. Discrepancies
are never "balanced" into any book, including the unattributed control book.

Freeze policy (owner decision, 2026-10-20):
- unexplained, account-wide or incomplete evidence -> freeze ALL SIM books;
- a proven book-specific mismatch freezes only that book, and only when every
  other strategy book is independently verified against broker order evidence
  and the account-level position difference is fully explained by it.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from sidedeck.domain.sim_accounting import (
    SIM_BOOKS, STRATEGY_BOOKS, SimAccountingError, SimEventType, SimLedger,
)
from sidedeck.infrastructure.saxo_operator_approval import valid_principal
from sidedeck.infrastructure.saxo_sim_journal import SimJournalStore

ZERO = Decimal("0")
# Process-local key: only reconcile_sim_account() can produce a report that
# release_freeze() will accept; a hand-built "MATCHED" report cannot unfreeze.
_REPORT_SEAL_KEY = secrets.token_bytes(32)


@dataclass(frozen=True)
class SimBrokerEvidence:
    account_id: str
    positions_response: dict[str, Any]
    order_fill_totals: Mapping[str, Decimal] | None = None   # order_key -> broker FillAmount total
    cash_change_eur: Decimal | None = None                   # broker cash change since books opened


@dataclass(frozen=True)
class SimReconciliationReport:
    status: str            # MATCHED | BOOK_MISMATCH | ACCOUNT_MISMATCH | INCOMPLETE
    freeze_scope: str      # NONE | BOOK | ACCOUNT
    frozen_books: tuple[str, ...]
    checked_at: datetime
    book_results: dict[str, str] = field(default_factory=dict)  # VERIFIED | MISMATCH | UNVERIFIED
    discrepancies: tuple[str, ...] = ()
    seal: str = field(default="", repr=False, compare=False)

    def _mac(self) -> str:
        material = json.dumps([self.status, self.freeze_scope, list(self.frozen_books),
                               self.checked_at.isoformat(), sorted(self.book_results.items()),
                               list(self.discrepancies)], separators=(",", ":"))
        return hmac.new(_REPORT_SEAL_KEY, material.encode("utf-8"), hashlib.sha256).hexdigest()

    def is_genuine(self) -> bool:
        return bool(self.seal) and hmac.compare_digest(self._mac(), self.seal)


def _sealed(report: SimReconciliationReport) -> SimReconciliationReport:
    return replace(report, seal=report._mac())


def parse_positions(response: dict[str, Any], account_id: str) -> dict[int, Decimal]:
    """Complete, account-scoped positions keyed by Uic; partial pages fail closed."""
    rows = response.get("Data") if isinstance(response, dict) else None
    if not isinstance(rows, list):
        raise SimAccountingError("positions response malformed")
    if response.get("__next") or (type(response.get("__count")) is int
                                   and response["__count"] != len(rows)):
        raise SimAccountingError("positions response incomplete")
    totals: dict[int, Decimal] = {}
    for row in rows:
        base = row.get("PositionBase") if isinstance(row, dict) else None
        if not isinstance(base, dict) or base.get("AccountId") != account_id:
            raise SimAccountingError("position does not belong to the SIM account")
        uic = base.get("Uic")
        if type(uic) is not int:
            raise SimAccountingError("position instrument missing")
        try:
            amount = Decimal(str(base.get("Amount")))
        except (InvalidOperation, ValueError) as exc:
            raise SimAccountingError("position amount invalid") from exc
        if not amount.is_finite():
            raise SimAccountingError("position amount invalid")
        totals[uic] = totals.get(uic, ZERO) + amount
    return totals


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


def reconcile_sim_account(ledger: SimLedger, evidence: SimBrokerEvidence, *, checked_at: datetime,
                          cash_tolerance_eur: Decimal = Decimal("1.00")) -> SimReconciliationReport:
    """Pure comparison; returns the freeze decision without changing anything."""
    if checked_at.tzinfo is None:
        raise SimAccountingError("reconciliation time must be timezone-aware")
    discrepancies: list[str] = []
    book_results: dict[str, str] = {}
    corrections: dict[int, Decimal] = {}   # broker evidence minus journal, per Uic, for mismatches
    for book in STRATEGY_BOOKS.values():
        result = "VERIFIED"
        for order_key, (uic, journal_qty) in sorted(_order_fills(ledger, book).items()):
            broker_qty = (None if evidence.order_fill_totals is None
                          else evidence.order_fill_totals.get(order_key))
            if broker_qty is None:
                result = "UNVERIFIED" if result == "VERIFIED" else result
                discrepancies.append(f"{book}: no broker fill evidence for {order_key}")
            elif broker_qty != journal_qty:
                result = "MISMATCH"
                corrections[uic] = corrections.get(uic, ZERO) + broker_qty - journal_qty
                discrepancies.append(f"{book}: {order_key} journal {journal_qty} vs broker {broker_qty}")
        book_results[book] = result

    broker = parse_positions(evidence.positions_response, evidence.account_id)
    internal = _internal_positions(ledger)
    position_diff = {uic: broker.get(uic, ZERO) - internal.get(uic, ZERO)
                     for uic in set(broker) | set(internal)
                     if broker.get(uic, ZERO) != internal.get(uic, ZERO)}
    for uic, diff in sorted(position_diff.items()):
        discrepancies.append(f"account: Uic {uic} broker minus books = {diff}")

    cash_mismatch = False
    if evidence.cash_change_eur is not None:
        spent = sum((ledger.replay(b).allocation_eur - ledger.replay(b).cash_eur
                     for b in STRATEGY_BOOKS.values()), ZERO)
        if abs(evidence.cash_change_eur + spent) > cash_tolerance_eur:
            cash_mismatch = True
            discrepancies.append(f"account: cash change {evidence.cash_change_eur} vs books {-spent}")

    mismatched = tuple(b for b, r in book_results.items() if r == "MISMATCH")
    unverified = [b for b, r in book_results.items() if r == "UNVERIFIED"]
    if not mismatched and not unverified and not position_diff and not cash_mismatch:
        return _sealed(SimReconciliationReport("MATCHED", "NONE", (), checked_at, book_results, ()))
    if mismatched:
        others_verified = all(book_results[b] == "VERIFIED"
                              for b in STRATEGY_BOOKS.values() if b not in mismatched)
        explained = position_diff == {u: d for u, d in corrections.items() if d != 0}
        if others_verified and explained and not cash_mismatch:
            return _sealed(SimReconciliationReport("BOOK_MISMATCH", "BOOK", mismatched, checked_at,
                                           book_results, tuple(discrepancies)))
        return _sealed(SimReconciliationReport("ACCOUNT_MISMATCH", "ACCOUNT", SIM_BOOKS, checked_at,
                                       book_results, tuple(discrepancies)))
    if position_diff or cash_mismatch:
        return _sealed(SimReconciliationReport("ACCOUNT_MISMATCH", "ACCOUNT", SIM_BOOKS, checked_at,
                                       book_results, tuple(discrepancies)))
    return _sealed(SimReconciliationReport("INCOMPLETE", "ACCOUNT", SIM_BOOKS, checked_at,
                                   book_results, tuple(discrepancies)))


def apply_reconciliation(store: SimJournalStore, report: SimReconciliationReport) -> None:
    """Record the run and freeze as decided. Never writes journal entries."""
    store.record_reconciliation(checked_at=report.checked_at, status=report.status,
                                scope=report.freeze_scope, frozen_books=report.frozen_books,
                                discrepancies=report.discrepancies)
    if report.freeze_scope != "NONE":
        store.freeze(report.frozen_books, scope=report.freeze_scope,
                     reason="; ".join(report.discrepancies)[:2000] or report.status,
                     at=report.checked_at)


def release_freeze(store: SimJournalStore, report: SimReconciliationReport, *,
                   released_by: str) -> tuple[str, ...]:
    """Unfreeze only after a later, fully MATCHED reconciliation and a named principal."""
    if not report.is_genuine():
        raise SimAccountingError("reconciliation report was not produced by reconcile_sim_account")
    if report.status != "MATCHED" or report.freeze_scope != "NONE":
        raise SimAccountingError("only a fully matched reconciliation can release a freeze")
    if not valid_principal(released_by):
        raise SimAccountingError("a named principal must release a freeze")
    frozen = {b: s for b, s in store.statuses().items() if s.status == "FROZEN"}
    checked = report.checked_at.astimezone(timezone.utc)
    for status in frozen.values():
        if status.frozen_at is None or checked <= datetime.fromisoformat(status.frozen_at):
            raise SimAccountingError("release needs a reconciliation run after the freeze")
    store.release(tuple(frozen), released_by=released_by)
    return tuple(frozen)
