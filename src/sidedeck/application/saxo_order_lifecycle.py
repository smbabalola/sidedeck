"""Durable broker order lifecycle journal for future Saxo SIM execution.

No HTTP, broker submission, retries, or account credentials are handled here.
UNKNOWN is intentionally sticky until independently reconciled with broker evidence.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

VALID_TRANSITIONS = {
    "STAGED": frozenset({"SUBMITTING", "CANCELLED"}),
    "SUBMITTING": frozenset({"UNKNOWN", "ACKNOWLEDGED", "REJECTED"}),
    "UNKNOWN": frozenset({"ACKNOWLEDGED", "REJECTED", "FILLED", "PARTIAL"}),
    "ACKNOWLEDGED": frozenset({"PARTIAL", "FILLED", "CANCELLED", "UNKNOWN"}),
    "PARTIAL": frozenset({"FILLED", "CANCELLED", "UNKNOWN"}),
    "FILLED": frozenset(),
    "CANCELLED": frozenset(),
    "REJECTED": frozenset(),
}


class LifecycleConflict(ValueError):
    pass


def _connect(path: str | Path) -> sqlite3.Connection:
    db = sqlite3.connect(str(path), timeout=10, isolation_level=None)
    db.execute("PRAGMA busy_timeout=10000")
    db.execute("CREATE TABLE IF NOT EXISTS broker_lifecycle ("
               "order_key TEXT PRIMARY KEY, status TEXT NOT NULL, "
               "broker_order_id TEXT UNIQUE, revision INTEGER NOT NULL)")
    return db


def create_lifecycle(path: str | Path, order_key: str) -> bool:
    if not order_key or len(order_key) > 100 or not order_key.isascii() or not all(
        ch.isalnum() or ch in "-_" for ch in order_key
    ):
        raise ValueError("invalid order key")
    with _connect(path) as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            existing = db.execute("SELECT status FROM broker_lifecycle WHERE order_key=?",
                                  (order_key,)).fetchone()
            if existing:
                db.commit()
                return False
            db.execute("INSERT INTO broker_lifecycle VALUES (?, 'STAGED', NULL, 0)",
                       (order_key,))
            db.commit()
            return True
        except BaseException:
            db.rollback()
            raise


def advance_lifecycle(path: str | Path, order_key: str, new_status: str,
                      *, broker_order_id: str | None = None,
                      broker_evidence: bool = False) -> int:
    """Atomic transition. Unknown outcomes require broker evidence before advancing."""
    with _connect(path) as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            row = db.execute(
                "SELECT status, broker_order_id, revision FROM broker_lifecycle WHERE order_key=?",
                (order_key,),
            ).fetchone()
            if row is None:
                raise LifecycleConflict("unregistered order intent")
            previous, current_broker_id, revision = row
            if new_status not in VALID_TRANSITIONS.get(previous, frozenset()):
                raise LifecycleConflict("unapproved lifecycle transition")
            if previous == "UNKNOWN" and not broker_evidence:
                raise LifecycleConflict("unknown submission requires broker evidence")
            if new_status in {"ACKNOWLEDGED", "PARTIAL", "FILLED"}:
                if not broker_evidence:
                    raise LifecycleConflict("broker evidence required for execution state")
                if not (broker_order_id or current_broker_id):
                    raise LifecycleConflict("broker order identifier required")
            if broker_order_id is not None:
                if not broker_order_id or len(broker_order_id) > 128:
                    raise LifecycleConflict("invalid broker order identifier")
                if current_broker_id and broker_order_id != current_broker_id:
                    raise LifecycleConflict("broker order identifier changed")
            chosen_id = current_broker_id or broker_order_id
            try:
                db.execute(
                    "UPDATE broker_lifecycle SET status=?, broker_order_id=?, revision=? "
                    "WHERE order_key=?",
                    (new_status, chosen_id, revision + 1, order_key),
                )
            except sqlite3.IntegrityError as exc:
                raise LifecycleConflict("broker order ID already associated") from exc
            db.commit()
            return revision + 1
        except BaseException:
            db.rollback()
            raise


def lifecycle_state(path: str | Path, order_key: str) -> tuple[str, str | None, int] | None:
    with _connect(path) as db:
        row = db.execute("SELECT status, broker_order_id, revision "
                         "FROM broker_lifecycle WHERE order_key=?", (order_key,)).fetchone()
        if row is None:
            return None
        return str(row[0]), row[1], int(row[2])
