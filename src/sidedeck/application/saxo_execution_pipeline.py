"""Connect Saxo execution evidence to the isolated SideDeck ledger.

This is intentionally an injected, offline-capable pipeline. It accepts only
account-scoped, identity-matched execution records and converts EUR execution
values to USD using the same validated FX evidence used at order preparation.
"""
from __future__ import annotations

import sqlite3
import json
import hashlib
from threading import Lock
from uuid import NAMESPACE_URL, uuid5
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from sidedeck.application.saxo_execution_history import BrokerExecution
from sidedeck.application.saxo_market_data import FxSnapshot
from sidedeck.application.saxo_order_lifecycle import advance_lifecycle, lifecycle_state
from sidedeck.domain.accounting import Ledger, fill_event
from sidedeck.domain.contracts import EventType, LedgerEvent


@dataclass(frozen=True)
class AppliedExecution:
    execution_id: str
    portfolio_id: str
    quantity: Decimal
    price_usd: Decimal
    fee_usd: Decimal
    duplicate: bool


class SaxoExecutionPipeline:
    def __init__(self, db_path: str, ledger: Ledger) -> None:
        self._db_path = db_path
        self._ledger = ledger
        self._recover_lock = Lock()
        with sqlite3.connect(db_path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS saxo_execution_recovery ("
                       "execution_id TEXT PRIMARY KEY, order_key TEXT NOT NULL, "
                       "portfolio_id TEXT NOT NULL, event_payload TEXT NOT NULL, "
                       "event_sha256 TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('PENDING','RECOVERING','POSTED')), "
                       "broker_order_id TEXT NOT NULL, fill_status TEXT NOT NULL, claimed_at TEXT, "
                       "authorized_quantity TEXT NOT NULL DEFAULT '1')")

    def _advance_lifecycle(self, order_key: str, order_id: str, status: str) -> None:
        state = lifecycle_state(self._db_path, order_key)
        target = "FILLED" if status == "FinalFill" else "PARTIAL"
        if state and state[0] in {"ACKNOWLEDGED", "PARTIAL"} and state[0] != target:
            advance_lifecycle(self._db_path, order_key,
                              target,
                              broker_order_id=order_id, broker_evidence=True)

    def recover(self) -> int:
        """Replay all durable pending/posted records after a crash."""
        with self._recover_lock, sqlite3.connect(self._db_path) as db:
            rows = db.execute("SELECT execution_id, order_key, portfolio_id, event_payload, status, "
                             "broker_order_id, fill_status "
                             "FROM saxo_execution_recovery WHERE status IN ('PENDING','RECOVERING','POSTED') "
                             "ORDER BY execution_id").fetchall()
        recovered = 0
        for execution_id, order_key, portfolio_id, payload, status, broker_order_id, fill_status in rows:
            event = LedgerEvent.model_validate(json.loads(payload))
            if status in {"PENDING", "RECOVERING"}:
                with sqlite3.connect(self._db_path, isolation_level="IMMEDIATE") as db:
                    claimed = db.execute("UPDATE saxo_execution_recovery SET status='RECOVERING', claimed_at=? "
                                         "WHERE execution_id=? AND status='PENDING'",
                                         (datetime.now(timezone.utc).isoformat(), execution_id)).rowcount
                if not claimed and status == "PENDING":
                    continue
                appended = self._ledger.append(event)
                with sqlite3.connect(self._db_path) as db:
                    db.execute("UPDATE saxo_execution_recovery SET status='POSTED' WHERE execution_id=?",
                               (execution_id,))
                recovered += int(appended)
            else:
                recovered += int(self._ledger.append(event))
            authorized = Decimal("1")
            with sqlite3.connect(self._db_path) as db:
                quantity_row = db.execute("SELECT authorized_quantity FROM saxo_execution_recovery "
                                          "WHERE execution_id=?", (execution_id,)).fetchone()
                if quantity_row and quantity_row[0] is not None:
                    authorized = Decimal(str(quantity_row[0]))
                total_row = db.execute("SELECT event_payload FROM saxo_execution_recovery "
                                       "WHERE order_key=? AND portfolio_id=? AND status='POSTED'",
                                       (order_key, portfolio_id)).fetchall()
            total = sum((Decimal(str(LedgerEvent.model_validate(json.loads(item[0])).quantity or 0))
                         for item in total_row), Decimal("0"))
            if fill_status != "FinalFill" or total == authorized:
                self._advance_lifecycle(order_key, broker_order_id, fill_status)
        return recovered

    def apply_buy_fill(
        self,
        execution: BrokerExecution,
        *,
        order_key: str,
        portfolio_id: str,
        fx: FxSnapshot,
        account_id: str,
        now: datetime,
        authorized_quantity: Decimal = Decimal("1"),
    ) -> AppliedExecution:
        """Atomically deduplicate external fills before mutating the ledger."""
        if execution.account_id != account_id or execution.external_reference != order_key:
            raise ValueError("execution is not matched to the requested account/order")
        if not authorized_quantity.is_finite() or authorized_quantity <= 0:
            raise ValueError("authorized execution quantity is invalid")
        if (execution.status not in {"Fill", "FinalFill"}
                or execution.instrument_currency != "USD"
                or execution.account_currency != "EUR"
                or execution.price_currency != "USD"):
            raise ValueError("execution currency metadata is not supported")
        if fx.pair != "EUR/USD":
            raise ValueError("EUR/USD conversion is required")
        price_usd = execution.price
        if execution.fees_currency == "EUR":
            fee_usd = execution.fees * fx.usd_per_eur
        elif execution.fees_currency == "USD":
            fee_usd = execution.fees
        else:
            raise ValueError("fee currency has no approved conversion")
        event_time = datetime.fromisoformat(execution.occurred_at.replace("Z", "+00:00"))
        event_time = event_time.astimezone(timezone.utc)
        event = fill_event(portfolio_id, "saxo:" + execution.execution_id,
                           EventType.BUY_FILL, "US:SOFI", execution.quantity,
                           price_usd, event_time, fee_usd)
        event = event.model_copy(update={
            "operation_id": uuid5(NAMESPACE_URL, "sidedeck:saxo-operation:" + execution.execution_id),
            "event_id": uuid5(NAMESPACE_URL, "sidedeck:saxo-execution:" + execution.execution_id)
        })
        event_payload = event.model_dump_json()
        event_sha256 = hashlib.sha256(event_payload.encode("utf-8")).hexdigest()
        duplicate = False
        with sqlite3.connect(self._db_path, isolation_level="IMMEDIATE") as db:
            prior_rows = db.execute("SELECT event_payload FROM saxo_execution_recovery "
                                    "WHERE order_key=? AND portfolio_id=? AND status='POSTED'",
                                    (order_key, portfolio_id)).fetchall()
            prior_quantity = sum((Decimal(str(LedgerEvent.model_validate(json.loads(row[0])).quantity or 0))
                                  for row in prior_rows), Decimal("0"))
            row = db.execute("SELECT order_key, portfolio_id, event_sha256, event_payload, status FROM saxo_execution_recovery "
                             "WHERE execution_id=?", (execution.execution_id,)).fetchone()
            if row is not None:
                if row[0] != order_key or row[1] != portfolio_id:
                    raise ValueError("execution ID was reused across orders or portfolios")
                if row[2] != event_sha256 or row[3] != event_payload:
                    raise ValueError("execution ID was reused with different economic payload")
                status = row[4]
                if status == "PENDING":
                    self._ledger.append(event)
                    db.execute("UPDATE saxo_execution_recovery SET status='POSTED' WHERE execution_id=?",
                               (execution.execution_id,))
                duplicate = True
            else:
                cumulative = prior_quantity + execution.quantity
                if cumulative > authorized_quantity:
                    raise ValueError("execution quantity exceeds authorized order quantity")
                if execution.status == "FinalFill" and cumulative != authorized_quantity:
                    raise ValueError("final fill does not reconcile to authorized order quantity")
                db.execute("INSERT INTO saxo_execution_recovery "
                           "(execution_id, order_key, portfolio_id, event_payload, event_sha256, status, "
                           "broker_order_id, fill_status, claimed_at, authorized_quantity) "
                           "VALUES (?, ?, ?, ?, ?, 'PENDING', ?, ?, NULL, ?)",
                           (execution.execution_id, order_key, portfolio_id, event_payload,
                            event_sha256, execution.order_id, execution.status, str(authorized_quantity)))
        if not duplicate:
            # The PENDING row is durable before the in-memory ledger changes.
            self._ledger.append(event)
            with sqlite3.connect(self._db_path) as db:
                db.execute("UPDATE saxo_execution_recovery SET status='POSTED' WHERE execution_id=?",
                           (execution.execution_id,))
        if execution.status != "FinalFill" or prior_quantity + execution.quantity == authorized_quantity:
            self._advance_lifecycle(order_key, execution.order_id, execution.status)
        return AppliedExecution(execution.execution_id, portfolio_id,
                                execution.quantity, price_usd, fee_usd, duplicate)
