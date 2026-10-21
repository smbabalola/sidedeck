"""Durable, transport-free paper intent outbox.

This module records intent and simulated dispatcher state only.  It has no
broker client, credentials, HTTP path or order submission capability.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, cast


class IntentError(ValueError):
    """A durable intent or state transition is invalid."""


@dataclass(frozen=True)
class PaperIntent:
    intent_id: str
    client_order_id: str
    tenant: str
    broker: str
    environment: str
    account_scope: str
    portfolio_id: str
    instrument_id: str
    side: str
    quantity: Decimal
    limit_price: Decimal


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DurablePaperIntentStore:
    """SQLite append-only intent/event store with atomic idempotency."""

    def __init__(self, path: str) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(target, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS paper_intents (
              intent_id TEXT PRIMARY KEY, client_order_id TEXT NOT NULL UNIQUE,
              tenant TEXT NOT NULL, broker TEXT NOT NULL, environment TEXT NOT NULL,
              account_scope TEXT NOT NULL, portfolio_id TEXT NOT NULL,
              instrument_id TEXT NOT NULL, side TEXT NOT NULL,
              quantity TEXT NOT NULL, limit_price TEXT NOT NULL,
              filled_quantity TEXT NOT NULL DEFAULT '0',
              state TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS paper_intent_events (
              sequence INTEGER PRIMARY KEY AUTOINCREMENT, intent_id TEXT NOT NULL,
              event_type TEXT NOT NULL, payload TEXT NOT NULL, occurred_at TEXT NOT NULL,
              FOREIGN KEY(intent_id) REFERENCES paper_intents(intent_id)
            );
            CREATE UNIQUE INDEX IF NOT EXISTS uq_paper_intent_event
              ON paper_intent_events(intent_id, event_type, payload);
            """
        )

    def close(self) -> None:
        self._db.close()

    def enqueue(self, intent: PaperIntent) -> dict[str, Any]:
        self._validate(intent)
        payload = self._payload(intent)
        try:
            self._db.execute("BEGIN IMMEDIATE")
            existing = self._db.execute(
                "SELECT * FROM paper_intents WHERE client_order_id=?", (intent.client_order_id,)
            ).fetchone()
            if existing is not None:
                if any(existing[key] != payload[key] for key in payload):
                    raise IntentError("conflicting client order idempotency key")
                self._db.execute("COMMIT")
                return self.get(intent.intent_id)
            self._db.execute(
                "INSERT INTO paper_intents(intent_id,client_order_id,tenant,broker,environment,account_scope,portfolio_id,instrument_id,side,quantity,limit_price,filled_quantity,state,created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (intent.intent_id, intent.client_order_id, intent.tenant, intent.broker,
                 intent.environment, intent.account_scope, intent.portfolio_id,
                 intent.instrument_id, intent.side, str(intent.quantity), str(intent.limit_price),
                 "0", "QUEUED", _utc_now()),
            )
            self._append(intent.intent_id, "INTENT_QUEUED", payload)
            self._db.execute("COMMIT")
            return self.get(intent.intent_id)
        except sqlite3.IntegrityError as exc:
            self._rollback()
            raise IntentError("conflicting durable intent") from exc
        except Exception:
            self._rollback()
            raise

    def claim(self, intent_id: str) -> dict[str, Any]:
        return self._transition(intent_id, "CLAIMED", {"from": "QUEUED"})

    def record_simulated_submission(self, intent_id: str) -> dict[str, Any]:
        """Record one local dry-run submission; never contacts a broker."""
        return self._transition(intent_id, "SUBMITTED_SIMULATED", {"from": "CLAIMED"})

    def acknowledge(self, intent_id: str, broker_reference: str = "offline-simulated") -> dict[str, Any]:
        if not broker_reference or broker_reference != "offline-simulated":
            raise IntentError("only the local simulated acknowledgement is permitted")
        return self._transition(intent_id, "ACKED_SIMULATED", {"from": "SUBMITTED_SIMULATED"})

    def record_fill(self, intent_id: str, quantity: Decimal) -> dict[str, Any]:
        if not quantity.is_finite() or quantity <= 0:
            raise IntentError("fill quantity must be positive and finite")
        row = self._row(intent_id)
        if row["state"] not in {"ACKED_SIMULATED", "PARTIALLY_FILLED_SIMULATED"}:
            raise IntentError("invalid transition to simulated fill")
        current = Decimal(row["filled_quantity"]) if "filled_quantity" in row.keys() else Decimal("0")
        requested = Decimal(row["quantity"])
        filled = current + quantity
        if filled > requested:
            raise IntentError("fill exceeds intent quantity")
        state = "FILLED_SIMULATED" if filled == requested else "PARTIALLY_FILLED_SIMULATED"
        self._db.execute("BEGIN IMMEDIATE")
        try:
            self._db.execute("UPDATE paper_intents SET state=?, filled_quantity=? WHERE intent_id=?",
                             (state, str(filled), intent_id))
            self._append(intent_id, "FILL_SIMULATED", {"quantity": str(quantity), "total": str(filled)})
            self._db.execute("COMMIT")
        except Exception:
            self._rollback()
            raise
        return self.get(intent_id)

    def record_rejection(self, intent_id: str, reason: str) -> dict[str, Any]:
        """Terminal no-fill outcome (broker rejected, cancelled, expired or never received)."""
        if not reason.strip():
            raise IntentError("a rejection reason is required")
        row = self._row(intent_id)
        if row["state"] not in {"CLAIMED", "SUBMITTED_SIMULATED", "ACKED_SIMULATED"}:
            raise IntentError(f"invalid transition from {row['state']} to REJECTED_SIMULATED")
        self._db.execute("BEGIN IMMEDIATE")
        try:
            self._db.execute("UPDATE paper_intents SET state='REJECTED_SIMULATED' WHERE intent_id=?",
                             (intent_id,))
            self._append(intent_id, "REJECTED_SIMULATED", {"reason": reason})
            self._db.execute("COMMIT")
        except Exception:
            self._rollback()
            raise
        return self.get(intent_id)

    def recover(self) -> list[dict[str, Any]]:
        """Return durable states after a process restart without side effects."""
        rows = self._db.execute("SELECT * FROM paper_intents ORDER BY created_at, intent_id").fetchall()
        return [dict(row) for row in rows]

    def events(self, intent_id: str) -> list[dict[str, Any]]:
        rows = self._db.execute(
            "SELECT sequence, event_type, payload, occurred_at FROM paper_intent_events "
            "WHERE intent_id=? ORDER BY sequence", (intent_id,)
        ).fetchall()
        return [{**dict(row), "payload": json.loads(row["payload"])} for row in rows]

    def get(self, intent_id: str) -> dict[str, Any]:
        row = self._row(intent_id)
        return dict(row)

    def _transition(self, intent_id: str, state: str, detail: dict[str, str]) -> dict[str, Any]:
        row = self._row(intent_id)
        allowed = {"CLAIMED": "QUEUED", "SUBMITTED_SIMULATED": "CLAIMED", "ACKED_SIMULATED": "SUBMITTED_SIMULATED"}
        if row["state"] != allowed[state]:
            raise IntentError(f"invalid transition from {row['state']} to {state}")
        self._db.execute("BEGIN IMMEDIATE")
        try:
            self._db.execute("UPDATE paper_intents SET state=? WHERE intent_id=?", (state, intent_id))
            self._append(intent_id, state, detail)
            self._db.execute("COMMIT")
        except Exception:
            self._rollback()
            raise
        return self.get(intent_id)

    def _append(self, intent_id: str, event_type: str, payload: dict[str, Any]) -> None:
        self._db.execute(
            "INSERT INTO paper_intent_events(intent_id,event_type,payload,occurred_at) VALUES (?,?,?,?)",
            (intent_id, event_type, json.dumps(payload, sort_keys=True), _utc_now()),
        )

    def _row(self, intent_id: str) -> sqlite3.Row:
        row = self._db.execute("SELECT * FROM paper_intents WHERE intent_id=?", (intent_id,)).fetchone()
        if row is None:
            raise IntentError("unknown durable intent")
        return cast(sqlite3.Row, row)

    def _rollback(self) -> None:
        if self._db.in_transaction:
            self._db.execute("ROLLBACK")

    @staticmethod
    def _payload(intent: PaperIntent) -> dict[str, Any]:
        return {"intent_id": intent.intent_id, "tenant": intent.tenant, "broker": intent.broker,
                "environment": intent.environment, "account_scope": intent.account_scope,
                "portfolio_id": intent.portfolio_id, "instrument_id": intent.instrument_id,
                "side": intent.side, "quantity": str(intent.quantity), "limit_price": str(intent.limit_price)}

    @staticmethod
    def _validate(intent: PaperIntent) -> None:
        values = (intent.intent_id, intent.client_order_id, intent.tenant, intent.broker,
                  intent.environment, intent.account_scope, intent.portfolio_id, intent.instrument_id)
        if any(not value.strip() for value in values) or intent.environment != "paper":
            raise IntentError("complete paper intent identity is required")
        if intent.side not in {"BUY", "SELL"} or not intent.quantity.is_finite() or intent.quantity <= 0:
            raise IntentError("side and positive finite quantity are required")
        if not intent.limit_price.is_finite() or intent.limit_price <= 0:
            raise IntentError("positive finite limit price is required")
