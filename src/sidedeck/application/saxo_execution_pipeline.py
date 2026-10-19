"""Connect Saxo execution evidence to the isolated SideDeck ledger.

This is intentionally an injected, offline-capable pipeline. It accepts only
account-scoped, identity-matched execution records and converts EUR execution
values to USD using the same validated FX evidence used at order preparation.
"""
from __future__ import annotations

import sqlite3
import json
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
        with sqlite3.connect(db_path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS saxo_execution_ids ("
                       "execution_id TEXT PRIMARY KEY, order_key TEXT NOT NULL, "
                       "portfolio_id TEXT NOT NULL, event_payload TEXT NOT NULL, "
                       "status TEXT NOT NULL CHECK(status IN ('PENDING','POSTED')), "
                       "broker_order_id TEXT NOT NULL, fill_status TEXT NOT NULL)")

    def _advance_lifecycle(self, order_key: str, order_id: str, status: str) -> None:
        state = lifecycle_state(self._db_path, order_key)
        if state and state[0] in {"ACKNOWLEDGED", "PARTIAL"}:
            advance_lifecycle(self._db_path, order_key,
                              "FILLED" if status == "FinalFill" else "PARTIAL",
                              broker_order_id=order_id, broker_evidence=True)

    def recover(self) -> int:
        """Replay all durable pending/posted records after a crash."""
        with sqlite3.connect(self._db_path) as db:
            rows = db.execute("SELECT execution_id, order_key, portfolio_id, event_payload, status, "
                             "broker_order_id, fill_status "
                             "FROM saxo_execution_ids ORDER BY execution_id").fetchall()
        recovered = 0
        for execution_id, order_key, portfolio_id, payload, status, broker_order_id, fill_status in rows:
            event = LedgerEvent.model_validate(json.loads(payload))
            if status == "PENDING":
                self._ledger.append(event)
                with sqlite3.connect(self._db_path) as db:
                    db.execute("UPDATE saxo_execution_ids SET status='POSTED' WHERE execution_id=?",
                               (execution_id,))
                recovered += 1
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
    ) -> AppliedExecution:
        """Atomically deduplicate external fills before mutating the ledger."""
        if execution.account_id != account_id or execution.external_reference != order_key:
            raise ValueError("execution is not matched to the requested account/order")
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
        event_payload = event.model_dump_json()
        duplicate = False
        with sqlite3.connect(self._db_path, isolation_level="IMMEDIATE") as db:
            row = db.execute("SELECT order_key, portfolio_id FROM saxo_execution_ids "
                             "WHERE execution_id=?", (execution.execution_id,)).fetchone()
            if row is not None:
                if row != (order_key, portfolio_id):
                    raise ValueError("execution ID was reused across orders or portfolios")
                status = db.execute("SELECT status FROM saxo_execution_ids WHERE execution_id=?",
                                   (execution.execution_id,)).fetchone()[0]
                if status == "PENDING":
                    self._ledger.append(event)
                    db.execute("UPDATE saxo_execution_ids SET status='POSTED' WHERE execution_id=?",
                               (execution.execution_id,))
                duplicate = True
            else:
                db.execute("INSERT INTO saxo_execution_ids VALUES (?, ?, ?, ?, 'PENDING', ?, ?)",
                           (execution.execution_id, order_key, portfolio_id, event_payload,
                            execution.order_id, execution.status))
        if not duplicate:
            # The PENDING row is durable before the in-memory ledger changes.
            self._ledger.append(event)
            with sqlite3.connect(self._db_path) as db:
                db.execute("UPDATE saxo_execution_ids SET status='POSTED' WHERE execution_id=?",
                           (execution.execution_id,))
        self._advance_lifecycle(order_key, execution.order_id, execution.status)
        return AppliedExecution(execution.execution_id, portfolio_id,
                                execution.quantity, price_usd, fee_usd, duplicate)
