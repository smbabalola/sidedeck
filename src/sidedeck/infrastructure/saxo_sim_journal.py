"""Durable Saxo SIM books, journal, freezes and reconciliation runs (ADR-003).

Separate tables from the research ``journal_events``. The schema matches
migrations ``0009_saxo_sim_books`` and ``0010_sim_reconciliation_evidence``; the
``CREATE TABLE IF NOT EXISTS`` statements keep runtime parity for disposable
databases.

This module is storage only. Opening books, recording reconciliation runs,
freezing and releasing are private primitives that must run inside the
caller's ``transaction()``. The trust checks (sealed read-only broker evidence,
a signed operator release) live in ``sidedeck.application.saxo_sim_reconciliation``.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
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
    "freeze_scope TEXT NOT NULL, frozen_books TEXT NOT NULL, discrepancies TEXT NOT NULL, "
    "account_id TEXT, evidence_id TEXT UNIQUE, source TEXT, observed_at TEXT, "
    "journal_sha256 TEXT, evidence_sha256 TEXT)",
    "CREATE TABLE IF NOT EXISTS saxo_sim_account_openings ("
    "account_id TEXT PRIMARY KEY, scope_sha256 TEXT NOT NULL, evidence_id TEXT UNIQUE NOT NULL, "
    "source TEXT NOT NULL, observed_at TEXT NOT NULL, cash_balance_eur TEXT NOT NULL, "
    "positions TEXT NOT NULL, evidence_sha256 TEXT NOT NULL, approval_ref TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS saxo_sim_freeze_releases ("
    "release_id INTEGER PRIMARY KEY AUTOINCREMENT, released_at TEXT NOT NULL, "
    "released_by TEXT NOT NULL, report_id TEXT NOT NULL, books TEXT NOT NULL, "
    "attestation_sha256 TEXT NOT NULL)",
)
_RUN_EVIDENCE_COLUMNS = {"account_id", "evidence_id", "source", "observed_at",
                         "journal_sha256", "evidence_sha256"}


@dataclass(frozen=True)
class BookStatus:
    book_id: str
    strategy_id: str | None
    account_id: str
    status: str
    freeze_scope: str | None
    freeze_reason: str | None
    frozen_at: str | None


@dataclass(frozen=True)
class AccountOpening:
    account_id: str
    scope_sha256: str
    evidence_id: str
    source: str
    observed_at: datetime
    cash_balance_eur: Decimal
    positions: dict[int, Decimal]
    evidence_sha256: str
    approval_ref: str


@dataclass(frozen=True)
class RecordedRun:
    run_id: int
    status: str
    evidence_id: str | None
    account_id: str | None
    observed_at: datetime | None
    journal_sha256: str | None
    evidence_sha256: str | None


def connect(db_path: str) -> sqlite3.Connection:
    db = sqlite3.connect(db_path, timeout=10, isolation_level=None)
    db.execute("PRAGMA busy_timeout=10000")
    db.execute("PRAGMA foreign_keys=ON")
    # Check before creating anything, so an older schema is never half-upgraded.
    columns = {row[1] for row in db.execute("PRAGMA table_info(saxo_sim_reconciliation_runs)")}
    if columns and not _RUN_EVIDENCE_COLUMNS <= columns:
        db.close()
        raise SimAccountingError("SIM schema predates migration 0010; run alembic upgrade head")
    for statement in DDL:
        db.execute(statement)
    return db


def _utc(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SimAccountingError("time must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat()


def _require_transaction(db: sqlite3.Connection) -> None:
    if not db.in_transaction:
        raise SimAccountingError("SIM state changes must run inside an IMMEDIATE transaction")


class SimJournalStore:
    """SQLite-backed SIM journal; every write is one IMMEDIATE transaction."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        connect(db_path).close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """One IMMEDIATE transaction: everything inside commits together or not at all."""
        db = connect(self.db_path)
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.execute("COMMIT")
        except BaseException:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        finally:
            db.close()

    # --- opening (only from sealed account evidence; see the application layer)
    def _open_from_evidence(self, db: sqlite3.Connection, *, account_id: str, scope_sha256: str,
                            evidence_id: str, source: str, observed_at: datetime,
                            cash_balance_eur: Decimal, positions: Mapping[int, Decimal],
                            instrument_ids: Mapping[int, str], evidence_sha256: str,
                            approval_ref: str) -> bool:
        """Create the books, the two EUR 1,000 allocations and broker baselines once."""
        _require_transaction(db)
        if not account_id or not approval_ref or not evidence_id or not scope_sha256:
            raise SimAccountingError("account identity, evidence and owner approval are required")
        existing = self.opening(db)
        if existing is not None:
            if (existing.account_id, existing.scope_sha256) != (account_id, scope_sha256):
                raise SimAccountingError("SIM books already belong to a different account")
            return False
        if db.execute("SELECT 1 FROM saxo_sim_books LIMIT 1").fetchone():
            raise SimAccountingError("SIM books exist without verified opening evidence")
        at = _utc(observed_at)
        for strategy, book in (*STRATEGY_BOOKS.items(), (None, UNATTRIBUTED_BOOK)):
            db.execute("INSERT INTO saxo_sim_books (book_id, strategy_id, account_id, "
                       "account_currency, opened_at, status) VALUES (?, ?, ?, 'EUR', ?, 'OPEN')",
                       (book, strategy, account_id, at))
        events = [SimEvent(book_id=book, idempotency_key="allocation:initial",
                           event_type=SimEventType.SIM_ALLOCATION, occurred_at=observed_at,
                           allocation_eur=INITIAL_ALLOCATION_EUR, approval_ref=approval_ref)
                  for book in STRATEGY_BOOKS.values()]
        events += [SimEvent(book_id=UNATTRIBUTED_BOOK, idempotency_key=f"baseline:{uic}",
                            event_type=SimEventType.SIM_BASELINE, occurred_at=observed_at,
                            instrument_id=instrument_ids[uic], uic=uic, quantity=quantity,
                            approval_ref="evidence:" + evidence_id)
                   for uic, quantity in sorted(positions.items()) if quantity != 0]
        ledger = SimLedger()
        for event in events:
            ledger.append(event)
            self._insert(db, event, fill_status=None)
        db.execute("INSERT INTO saxo_sim_account_openings (account_id, scope_sha256, evidence_id, "
                   "source, observed_at, cash_balance_eur, positions, evidence_sha256, "
                   "approval_ref) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                   (account_id, scope_sha256, evidence_id, source, at, str(cash_balance_eur),
                    json.dumps({str(u): str(q) for u, q in sorted(positions.items())}),
                    evidence_sha256, approval_ref))
        return True

    def opening(self, db: sqlite3.Connection | None = None) -> AccountOpening | None:
        own = db is None
        conn = db or connect(self.db_path)
        try:
            rows = conn.execute("SELECT account_id, scope_sha256, evidence_id, source, observed_at, "
                                "cash_balance_eur, positions, evidence_sha256, approval_ref "
                                "FROM saxo_sim_account_openings").fetchall()
        finally:
            if own:
                conn.close()
        if not rows:
            return None
        if len(rows) != 1:
            raise SimAccountingError("more than one SIM account opening recorded")
        row = rows[0]
        positions = {int(uic): Decimal(qty) for uic, qty in json.loads(row[6]).items()}
        return AccountOpening(row[0], row[1], row[2], row[3], datetime.fromisoformat(row[4]),
                              Decimal(row[5]), positions, row[7], row[8])

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

    def _freeze(self, db: sqlite3.Connection, book_ids: tuple[str, ...], *, scope: str,
                reason: str, at: datetime) -> None:
        """Freeze inside the caller's transaction; never downgrades an ACCOUNT freeze."""
        _require_transaction(db)
        if scope not in ("BOOK", "ACCOUNT") or not reason or not book_ids:
            raise SimAccountingError("invalid freeze request")
        if any(book not in SIM_BOOKS for book in book_ids):
            raise SimAccountingError("not a Saxo SIM book")
        for book in book_ids:
            db.execute("UPDATE saxo_sim_books SET status='FROZEN', "
                       "freeze_scope=CASE WHEN freeze_scope='ACCOUNT' THEN 'ACCOUNT' ELSE ? END, "
                       "freeze_reason=?, frozen_at=?, released_by=NULL WHERE book_id=?",
                       (scope, reason, _utc(at), book))

    def _release(self, db: sqlite3.Connection, book_ids: tuple[str, ...], *, released_by: str,
                 report_id: str, attestation_sha256: str, at: datetime) -> None:
        _require_transaction(db)
        for book in book_ids:
            db.execute("UPDATE saxo_sim_books SET status='OPEN', freeze_scope=NULL, "
                       "freeze_reason=NULL, frozen_at=NULL, released_by=? WHERE book_id=?",
                       (released_by, book))
        db.execute("INSERT INTO saxo_sim_freeze_releases (released_at, released_by, report_id, "
                   "books, attestation_sha256) VALUES (?, ?, ?, ?, ?)",
                   (_utc(at), released_by, report_id, json.dumps(list(book_ids)),
                    attestation_sha256))

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
        _require_transaction(db)
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

    @staticmethod
    def journal_digest(db: sqlite3.Connection) -> str:
        """Digest of the persisted journal; any added or altered entry changes it."""
        digest = hashlib.sha256()
        for sequence, payload_sha256 in db.execute(
                "SELECT journal_sequence, payload_sha256 FROM saxo_sim_journal "
                "ORDER BY journal_sequence"):
            digest.update(f"{sequence}:{payload_sha256}\n".encode("ascii"))
        return digest.hexdigest()

    # --- reconciliation runs --------------------------------------------
    def _record_run(self, db: sqlite3.Connection, *, checked_at: datetime, status: str, scope: str,
                    frozen_books: tuple[str, ...], discrepancies: tuple[str, ...], account_id: str,
                    evidence_id: str, source: str, observed_at: datetime, journal_sha256: str,
                    evidence_sha256: str) -> None:
        _require_transaction(db)
        try:
            db.execute("INSERT INTO saxo_sim_reconciliation_runs (checked_at, status, freeze_scope, "
                       "frozen_books, discrepancies, account_id, evidence_id, source, observed_at, "
                       "journal_sha256, evidence_sha256) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       (_utc(checked_at), status, scope, json.dumps(list(frozen_books)),
                        json.dumps(list(discrepancies)), account_id, evidence_id, source,
                        _utc(observed_at), journal_sha256, evidence_sha256))
        except sqlite3.IntegrityError as exc:
            raise SimAccountingError("broker evidence was already used for a reconciliation") from exc

    @staticmethod
    def latest_run(db: sqlite3.Connection) -> RecordedRun | None:
        row = db.execute("SELECT run_id, status, evidence_id, account_id, observed_at, "
                         "journal_sha256, evidence_sha256 FROM saxo_sim_reconciliation_runs "
                         "ORDER BY run_id DESC LIMIT 1").fetchone()
        if row is None:
            return None
        observed = datetime.fromisoformat(row[4]) if row[4] else None
        return RecordedRun(row[0], row[1], row[2], row[3], observed, row[5], row[6])

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
