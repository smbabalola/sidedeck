"""Durable Saxo SIM books, journal, freezes and reconciliation runs (ADR-003).

Separate tables from the research ``journal_events``. The schema matches
migration ``0009_saxo_sim_books``; the ``CREATE TABLE IF NOT EXISTS``
statements keep runtime parity for disposable databases.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from sidedeck.domain.sim_accounting import (
    INITIAL_ALLOCATION_EUR, SIM_BOOKS, STRATEGY_BOOKS, UNATTRIBUTED_BOOK, SimAccountingError,
    SimEvent, SimEventType, SimLedger,
)

DDL = (
    "CREATE TABLE IF NOT EXISTS saxo_sim_books ("
    "book_id TEXT PRIMARY KEY, strategy_id TEXT, account_id TEXT NOT NULL, "
    "account_currency TEXT NOT NULL, opened_at TEXT NOT NULL, "
    "status TEXT NOT NULL CHECK(status IN ('OPEN','FROZEN','CLOSED')), "
    "freeze_scope TEXT CHECK(freeze_scope IN ('BOOK','ACCOUNT')), freeze_reason TEXT, "
    "frozen_at TEXT, released_by TEXT, UNIQUE(account_id, strategy_id))",
    "CREATE TABLE IF NOT EXISTS saxo_sim_journal ("
    "journal_sequence INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT UNIQUE NOT NULL, "
    "book_id TEXT NOT NULL REFERENCES saxo_sim_books(book_id), idempotency_key TEXT NOT NULL, "
    "event_type TEXT NOT NULL CHECK(event_type IN ('SIM_ALLOCATION','SIM_BUY_FILL','SIM_BASELINE')), "
    "order_key TEXT, broker_execution_id TEXT UNIQUE, fill_status TEXT, occurred_at TEXT NOT NULL, "
    "payload TEXT NOT NULL, payload_sha256 TEXT NOT NULL, UNIQUE(book_id, idempotency_key))",
    "CREATE TABLE IF NOT EXISTS saxo_sim_reconciliation_runs ("
    "run_id INTEGER PRIMARY KEY AUTOINCREMENT, checked_at TEXT NOT NULL, status TEXT NOT NULL, "
    "freeze_scope TEXT NOT NULL, frozen_books TEXT NOT NULL, discrepancies TEXT NOT NULL)",
)


@dataclass(frozen=True)
class BookStatus:
    book_id: str
    strategy_id: str | None
    account_id: str
    status: str
    freeze_scope: str | None
    freeze_reason: str | None
    frozen_at: str | None


def connect(db_path: str) -> sqlite3.Connection:
    db = sqlite3.connect(db_path, timeout=10, isolation_level=None)
    db.execute("PRAGMA busy_timeout=10000")
    db.execute("PRAGMA foreign_keys=ON")
    for statement in DDL:
        db.execute(statement)
    return db


def _utc(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SimAccountingError("time must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat()


class SimJournalStore:
    """SQLite-backed SIM journal; every write is one IMMEDIATE transaction."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        connect(db_path).close()

    # --- books -----------------------------------------------------------
    def open_books(self, *, account_id: str, opened_at: datetime, approval_ref: str) -> bool:
        """Create the three books and the two EUR 1,000 allocations once."""
        if not account_id or not approval_ref:
            raise SimAccountingError("account identity and owner approval reference are required")
        at = _utc(opened_at)
        db = connect(self.db_path)
        try:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("SELECT DISTINCT account_id FROM saxo_sim_books").fetchall()
            if rows:
                db.execute("ROLLBACK")
                if {row[0] for row in rows} != {account_id}:
                    raise SimAccountingError("SIM books already belong to a different account")
                return False
            for strategy, book in (*STRATEGY_BOOKS.items(), (None, UNATTRIBUTED_BOOK)):
                db.execute("INSERT INTO saxo_sim_books (book_id, strategy_id, account_id, "
                           "account_currency, opened_at, status) VALUES (?, ?, ?, 'EUR', ?, 'OPEN')",
                           (book, strategy, account_id, at))
            ledger = SimLedger()
            for book in STRATEGY_BOOKS.values():
                event = SimEvent(book_id=book, idempotency_key="allocation:initial",
                                 event_type=SimEventType.SIM_ALLOCATION, occurred_at=opened_at,
                                 allocation_eur=INITIAL_ALLOCATION_EUR, approval_ref=approval_ref)
                ledger.append(event)
                self._insert(db, event, fill_status=None)
            db.execute("COMMIT")
            return True
        except BaseException:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        finally:
            db.close()

    def record_baseline(self, *, instrument_id: str, uic: int, quantity: Decimal,
                        at: datetime, evidence_ref: str) -> bool:
        """Record pre-existing broker exposure once, in the unattributed control book only."""
        if not evidence_ref:
            raise SimAccountingError("baseline needs a read-only evidence reference")
        event = SimEvent(book_id=UNATTRIBUTED_BOOK, idempotency_key=f"baseline:{uic}",
                         event_type=SimEventType.SIM_BASELINE, occurred_at=at,
                         instrument_id=instrument_id, uic=uic, quantity=quantity,
                         approval_ref=evidence_ref)
        db = connect(self.db_path)
        try:
            db.execute("BEGIN IMMEDIATE")
            if set(self.statuses(db)) != set(SIM_BOOKS):
                raise SimAccountingError("Saxo SIM books are not opened")
            if db.execute("SELECT 1 FROM saxo_sim_journal WHERE book_id=? AND idempotency_key=?",
                          (UNATTRIBUTED_BOOK, event.idempotency_key)).fetchone():
                db.execute("ROLLBACK")
                return False
            self.load(db).check(event)
            self._insert(db, event, fill_status=None)
            db.execute("COMMIT")
            return True
        except BaseException:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        finally:
            db.close()

    def statuses(self, db: sqlite3.Connection | None = None) -> dict[str, BookStatus]:
        own = db is None
        conn = db or connect(self.db_path)
        try:
            rows = conn.execute("SELECT book_id, strategy_id, account_id, status, freeze_scope, "
                                "freeze_reason, frozen_at FROM saxo_sim_books").fetchall()
        finally:
            if own:
                conn.close()
        return {row[0]: BookStatus(*row) for row in rows}

    def require_tradable(self, book_id: str, db: sqlite3.Connection | None = None) -> None:
        """Fail closed unless the books exist, the account is unfrozen and the book is OPEN."""
        statuses = self.statuses(db)
        if set(statuses) != set(SIM_BOOKS):
            raise SimAccountingError("Saxo SIM books are not opened")
        if any(item.freeze_scope == "ACCOUNT" for item in statuses.values()):
            raise SimAccountingError("all Saxo SIM trading is frozen (account-wide mismatch)")
        if statuses[book_id].status != "OPEN":
            raise SimAccountingError("this Saxo SIM book is frozen")

    def freeze(self, book_ids: tuple[str, ...], *, scope: str, reason: str, at: datetime) -> None:
        if scope not in ("BOOK", "ACCOUNT") or not reason or not book_ids:
            raise SimAccountingError("invalid freeze request")
        if any(book not in SIM_BOOKS for book in book_ids):
            raise SimAccountingError("not a Saxo SIM book")
        db = connect(self.db_path)
        try:
            db.execute("BEGIN IMMEDIATE")
            for book in book_ids:
                db.execute("UPDATE saxo_sim_books SET status='FROZEN', freeze_scope=?, "
                           "freeze_reason=?, frozen_at=?, released_by=NULL WHERE book_id=?",
                           (scope, reason, _utc(at), book))
            db.execute("COMMIT")
        finally:
            if db.in_transaction:
                db.execute("ROLLBACK")
            db.close()

    def release(self, book_ids: tuple[str, ...], *, released_by: str) -> None:
        db = connect(self.db_path)
        try:
            db.execute("BEGIN IMMEDIATE")
            for book in book_ids:
                db.execute("UPDATE saxo_sim_books SET status='OPEN', freeze_scope=NULL, "
                           "freeze_reason=NULL, frozen_at=NULL, released_by=? WHERE book_id=?",
                           (released_by, book))
            db.execute("COMMIT")
        finally:
            if db.in_transaction:
                db.execute("ROLLBACK")
            db.close()

    # --- journal ---------------------------------------------------------
    @staticmethod
    def _insert(db: sqlite3.Connection, event: SimEvent, *, fill_status: str | None) -> None:
        db.execute("INSERT INTO saxo_sim_journal (event_id, book_id, idempotency_key, event_type, "
                   "order_key, broker_execution_id, fill_status, occurred_at, payload, "
                   "payload_sha256) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                   (event.event_id, event.book_id, event.idempotency_key, str(event.event_type),
                    event.order_key, event.broker_execution_id, fill_status,
                    event.occurred_at.isoformat(), event.canonical(), event.sha256()))

    def record_fill(self, db: sqlite3.Connection, event: SimEvent, *, fill_status: str) -> None:
        """Insert inside the caller's IMMEDIATE transaction."""
        self._insert(db, event, fill_status=fill_status)

    @staticmethod
    def load(db: sqlite3.Connection) -> SimLedger:
        """Deterministic, hash-verified replay in chronological order."""
        rows = db.execute("SELECT event_id, book_id, idempotency_key, payload, payload_sha256 "
                          "FROM saxo_sim_journal ORDER BY occurred_at, "
                          "CASE event_type WHEN 'SIM_ALLOCATION' THEN 0 ELSE 1 END, "
                          "idempotency_key").fetchall()
        ledger = SimLedger()
        for event_id, book_id, key, payload, digest in rows:
            if hashlib.sha256(payload.encode("utf-8")).hexdigest() != digest:
                raise SimAccountingError("persisted SIM event hash mismatch")
            event = SimEvent.from_canonical(payload)
            if (event.event_id, event.book_id, event.idempotency_key) != (event_id, book_id, key):
                raise SimAccountingError("persisted SIM event identity mismatch")
            ledger.append(event)
        return ledger

    def load_ledger(self) -> SimLedger:
        db = connect(self.db_path)
        try:
            return self.load(db)
        finally:
            db.close()

    # --- reconciliation runs --------------------------------------------
    def record_reconciliation(self, *, checked_at: datetime, status: str, scope: str,
                              frozen_books: tuple[str, ...], discrepancies: tuple[str, ...]) -> None:
        db = connect(self.db_path)
        try:
            db.execute("INSERT INTO saxo_sim_reconciliation_runs (checked_at, status, freeze_scope, "
                       "frozen_books, discrepancies) VALUES (?, ?, ?, ?, ?)",
                       (_utc(checked_at), status, scope, json.dumps(list(frozen_books)),
                        json.dumps(list(discrepancies))))
        finally:
            db.close()

    def last_reconciliation(self) -> dict[str, object] | None:
        db = connect(self.db_path)
        try:
            row = db.execute("SELECT checked_at, status, freeze_scope, frozen_books, discrepancies "
                             "FROM saxo_sim_reconciliation_runs ORDER BY run_id DESC LIMIT 1").fetchone()
        finally:
            db.close()
        if row is None:
            return None
        return {"checked_at": row[0], "status": row[1], "freeze_scope": row[2],
                "frozen_books": json.loads(row[3]), "discrepancies": json.loads(row[4])}
