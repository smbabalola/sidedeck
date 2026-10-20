"""Post Saxo SIM executions into the separate SIM books (ADR-003).

Fills are bound to the durable, operator-signed authorization: the book,
account, broker order, quantity and the validated EUR/USD rate all come from
that row, never from the caller. The journal insert is one IMMEDIATE SQLite
transaction, so a crash leaves either nothing or a complete, hash-verified
entry. The research ``Ledger`` and Alpaca paper accounts are not reachable
from this module.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_EVEN, Decimal

from sidedeck.application.saxo_execution_history import BrokerExecution
from sidedeck.application.saxo_order_lifecycle import (
    LifecycleConflict, advance_lifecycle, lifecycle_state,
)
from sidedeck.application.saxo_sim_submission import SOFI_UIC, ensure_authorization_table
from sidedeck.domain.sim_accounting import (
    SettlementSource, SimAccountingError, SimEvent, SimEventType, SimLedger, book_for_strategy,
)
from sidedeck.infrastructure.saxo_sim_journal import SimJournalStore, connect

EUR_PRECISION = Decimal("0.0001")
RECOVERY_DDL = (
    "CREATE TABLE IF NOT EXISTS saxo_execution_recovery ("
    "execution_id TEXT PRIMARY KEY, order_key TEXT NOT NULL, portfolio_id TEXT NOT NULL, "
    "event_payload TEXT NOT NULL, event_sha256 TEXT NOT NULL, "
    "status TEXT NOT NULL CHECK(status IN ('PENDING','RECOVERING','POSTED')), "
    "broker_order_id TEXT NOT NULL, fill_status TEXT NOT NULL, claimed_at TEXT, "
    "authorized_quantity TEXT NOT NULL DEFAULT '1', account_id TEXT NOT NULL DEFAULT '')"
)


@dataclass(frozen=True)
class AppliedExecution:
    execution_id: str
    book_id: str
    quantity: Decimal
    price_usd: Decimal
    settlement_eur: Decimal
    fee_eur: Decimal
    duplicate: bool


@dataclass(frozen=True)
class _Binding:
    authorization_id: str
    book_id: str
    quantity: Decimal
    fx_usd_per_eur: Decimal
    fx_provider: str


def _fill_quantity(ledger: SimLedger, order_key: str) -> Decimal:
    return sum((e.quantity or Decimal("0") for e in ledger.events
                if e.event_type is SimEventType.SIM_BUY_FILL and e.order_key == order_key),
               Decimal("0"))


class SaxoExecutionPipeline:
    """SIM-only fill posting; the only ledger it can reach is ``SimLedger``."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._store = SimJournalStore(db_path)
        with sqlite3.connect(db_path) as db:
            db.execute(RECOVERY_DDL)
            ensure_authorization_table(db)
            legacy = db.execute("SELECT COUNT(*) FROM saxo_execution_recovery").fetchone()[0]
        if legacy:
            raise SimAccountingError("legacy SIM fills were posted to research ledgers; "
                                     "owner review is required before SIM accounting can run")
        self.ledger: SimLedger = self._store.load_ledger()

    def _binding(self, db: sqlite3.Connection, order_key: str, *, account_id: str,
                 broker_order_id: str) -> _Binding:
        row = db.execute("SELECT authorization_id, portfolio_id, account_id, status, "
                         "broker_order_id, quantity, book_id, fx_usd_per_eur, fx_provider "
                         "FROM saxo_execution_authorization WHERE order_key=?",
                         (order_key,)).fetchone()
        if row is None or row[3] != "CONSUMED":
            raise SimAccountingError("execution has no consumed operator authorization")
        auth_id, strategy, bound_account, _, bound_order, quantity, book_id, fx, provider = row
        if bound_account != account_id:
            raise SimAccountingError("execution account differs from the authorization")
        if bound_order != broker_order_id:
            raise SimAccountingError("execution broker order ID does not match the authorization")
        if not book_id or book_id != book_for_strategy(strategy):
            raise SimAccountingError("authorization has no valid SIM strategy book")
        if not fx or not provider:
            raise SimAccountingError("authorization has no validated FX provenance")
        authorized = Decimal(str(quantity))
        rate = Decimal(str(fx))
        if (not authorized.is_finite() or authorized <= 0
                or authorized != authorized.to_integral_value()):
            raise SimAccountingError("authorized execution quantity is invalid")
        if not rate.is_finite() or rate <= 0:
            raise SimAccountingError("authorized FX rate is invalid")
        return _Binding(auth_id, book_id, authorized, rate, provider)

    def _advance_lifecycle(self, order_key: str, broker_order_id: str, *, final: bool) -> None:
        state = lifecycle_state(self._db_path, order_key)
        target = "FILLED" if final else "PARTIAL"
        if state and state[0] in {"ACKNOWLEDGED", "PARTIAL"} and state[0] != target:
            try:
                advance_lifecycle(self._db_path, order_key, target,
                                  broker_order_id=broker_order_id, broker_evidence=True)
            except LifecycleConflict:
                # A concurrent worker may have advanced the same order between our
                # read and write. Accept only if it reached this target or later.
                latest = lifecycle_state(self._db_path, order_key)
                reached = {"PARTIAL": {"PARTIAL", "FILLED"}, "FILLED": {"FILLED"}}[target]
                if latest is None or latest[0] not in reached or latest[1] != broker_order_id:
                    raise

    def recover(self) -> int:
        """Rebuild the SIM ledger from the journal and finish lifecycle updates.

        Idempotent and deterministic: replays chronologically, verifies every
        payload hash, and only moves lifecycles forward from journal facts.
        Returns the number of SIM fills in the rebuilt ledger.
        """
        db = connect(self._db_path)
        try:
            self.ledger = SimJournalStore.load(db)
            orders = db.execute("SELECT j.order_key, a.broker_order_id, a.quantity, "
                                "MAX(j.fill_status = 'FinalFill') FROM saxo_sim_journal j "
                                "JOIN saxo_execution_authorization a ON a.order_key = j.order_key "
                                "WHERE j.event_type = 'SIM_BUY_FILL' "
                                "GROUP BY j.order_key ORDER BY j.order_key").fetchall()
        finally:
            db.close()
        for order_key, broker_order_id, authorized, has_final in orders:
            total = _fill_quantity(self.ledger, order_key)
            final = bool(has_final) and total == Decimal(str(authorized))
            self._advance_lifecycle(order_key, broker_order_id, final=final)
        return sum(1 for e in self.ledger.events if e.event_type is SimEventType.SIM_BUY_FILL)

    def apply_buy_fill(self, execution: BrokerExecution, *, order_key: str, account_id: str,
                       now: datetime) -> AppliedExecution:
        """Atomically validate, deduplicate and journal one broker execution."""
        if execution.account_id != account_id or execution.external_reference != order_key:
            raise SimAccountingError("execution is not matched to the requested account/order")
        lifecycle = lifecycle_state(self._db_path, order_key)
        if lifecycle is None or lifecycle[0] not in {"ACKNOWLEDGED", "PARTIAL", "FILLED"}:
            raise SimAccountingError("execution requires an acknowledged broker order")
        if lifecycle[1] != execution.order_id:
            raise SimAccountingError("execution broker order ID does not match lifecycle")
        if (execution.status not in {"Fill", "FinalFill"}
                or execution.instrument_currency != "USD"
                or execution.account_currency != "EUR"
                or execution.price_currency != "USD"):
            raise SimAccountingError("execution currency metadata is not supported")
        event_time = datetime.fromisoformat(execution.occurred_at.replace("Z", "+00:00"))
        if event_time.tzinfo is None or event_time.utcoffset() is None:
            raise SimAccountingError("execution timestamp must carry a timezone")
        db = connect(self._db_path)
        try:
            db.execute("BEGIN IMMEDIATE")
            binding = self._binding(db, order_key, account_id=account_id,
                                    broker_order_id=execution.order_id)
            gross_usd = execution.quantity * execution.price
            settlement_eur = (gross_usd / binding.fx_usd_per_eur).quantize(
                EUR_PRECISION, ROUND_HALF_EVEN)
            if execution.fees_currency == "EUR":
                fee_eur = execution.fees
            elif execution.fees_currency == "USD":
                fee_eur = (execution.fees / binding.fx_usd_per_eur).quantize(
                    EUR_PRECISION, ROUND_HALF_EVEN)
            else:
                raise SimAccountingError("fee currency has no approved conversion")
            event = SimEvent(
                book_id=binding.book_id, idempotency_key="saxo:" + execution.execution_id,
                event_type=SimEventType.SIM_BUY_FILL, occurred_at=event_time,
                order_key=order_key, broker_execution_id=execution.execution_id,
                instrument_id="US:SOFI", uic=SOFI_UIC, quantity=execution.quantity,
                price_usd=execution.price, fx_usd_per_eur=binding.fx_usd_per_eur,
                fx_provider=binding.fx_provider, settlement_eur=settlement_eur,
                settlement_source=SettlementSource.DERIVED_FX, fee_amount=execution.fees,
                fee_currency=execution.fees_currency, fee_eur=fee_eur,
                approval_ref=binding.authorization_id)
            existing = db.execute("SELECT payload, book_id, order_key FROM saxo_sim_journal "
                                  "WHERE broker_execution_id=?",
                                  (execution.execution_id,)).fetchone()
            ledger = SimJournalStore.load(db)
            prior = _fill_quantity(ledger, order_key)
            if existing is not None:
                if existing[1] != binding.book_id or existing[2] != order_key:
                    raise SimAccountingError("execution ID was reused across orders or books")
                if existing[0] != event.canonical():
                    raise SimAccountingError("execution ID was reused with different economic payload")
                db.execute("ROLLBACK")
                duplicate = True
                cumulative = prior
            else:
                self._store.require_tradable(binding.book_id, db)
                if lifecycle[0] == "FILLED":
                    raise SimAccountingError("order is already filled")
                cumulative = prior + execution.quantity
                if cumulative > binding.quantity:
                    raise SimAccountingError("execution quantity exceeds authorized order quantity")
                if execution.status == "FinalFill" and cumulative != binding.quantity:
                    raise SimAccountingError("final fill does not reconcile to authorized order quantity")
                ledger.check(event)
                self._store.record_fill(db, event, fill_status=execution.status)
                db.execute("COMMIT")
                duplicate = False
        except BaseException:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        finally:
            db.close()
        self.ledger = self._store.load_ledger()
        has_final = execution.status == "FinalFill" or self._journal_has_final(order_key)
        self._advance_lifecycle(order_key, execution.order_id,
                                final=has_final and cumulative == binding.quantity)
        return AppliedExecution(execution.execution_id, binding.book_id, execution.quantity,
                                execution.price, settlement_eur, fee_eur, duplicate)

    def _journal_has_final(self, order_key: str) -> bool:
        db = connect(self._db_path)
        try:
            row = db.execute("SELECT 1 FROM saxo_sim_journal WHERE order_key=? "
                             "AND fill_status='FinalFill' LIMIT 1", (order_key,)).fetchone()
        finally:
            db.close()
        return row is not None
