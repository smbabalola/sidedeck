"""Connect Saxo execution evidence to the isolated SideDeck ledger.

This is intentionally an injected, offline-capable pipeline. It accepts only
account-scoped, identity-matched execution records and converts EUR execution
values to USD using the same validated FX evidence used at order preparation.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from sidedeck.application.saxo_execution_history import BrokerExecution
from sidedeck.application.saxo_market_data import FxSnapshot
from sidedeck.application.saxo_order_lifecycle import advance_lifecycle, lifecycle_state
from sidedeck.domain.accounting import Ledger, fill_event
from sidedeck.domain.contracts import EventType


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
                       "portfolio_id TEXT NOT NULL)")

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
        if execution.status not in {"Fill", "FinalFill"} or execution.currency != "EUR":
            raise ValueError("execution is not a supported EUR buy fill")
        if fx.pair != "EUR/USD":
            raise ValueError("EUR/USD conversion is required")
        price_usd = execution.price * fx.usd_per_eur
        fee_usd = execution.fees * fx.usd_per_eur
        with sqlite3.connect(self._db_path, isolation_level="IMMEDIATE") as db:
            row = db.execute("SELECT order_key, portfolio_id FROM saxo_execution_ids "
                             "WHERE execution_id=?", (execution.execution_id,)).fetchone()
            if row is not None:
                if row != (order_key, portfolio_id):
                    raise ValueError("execution ID was reused across orders or portfolios")
                return AppliedExecution(execution.execution_id, portfolio_id,
                                        execution.quantity, price_usd, fee_usd, True)
            event_time = datetime.fromisoformat(execution.occurred_at.replace("Z", "+00:00"))
            event_time = event_time.astimezone(timezone.utc)
            event = fill_event(portfolio_id, "saxo:" + execution.execution_id,
                               EventType.BUY_FILL, "US:SOFI", execution.quantity,
                               price_usd, event_time, fee_usd)
            self._ledger.append(event)
            db.execute("INSERT INTO saxo_execution_ids VALUES (?, ?, ?)",
                       (execution.execution_id, order_key, portfolio_id))
        state = lifecycle_state(self._db_path, order_key)
        if state and state[0] in {"ACKNOWLEDGED", "PARTIAL"}:
            advance_lifecycle(self._db_path, order_key,
                              "FILLED" if execution.status == "FinalFill" else "PARTIAL",
                              broker_order_id=execution.order_id, broker_evidence=True)
        return AppliedExecution(execution.execution_id, portfolio_id,
                                execution.quantity, price_usd, fee_usd, False)
