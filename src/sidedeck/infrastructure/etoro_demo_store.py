"""Local SQLite store for the eToro DEMO baseline and strategy attributions.

Matches migration ``0005_etoro_demo_books``. Holds broker position/order IDs,
so it lives only in the local, git-ignored database; never in GitHub or CI.
Writes are single IMMEDIATE transactions. The baseline is captured once (an
empty account is still a captured baseline) and is immutable; attributions
are append-only and can never name a baseline order or the unattributed book.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from decimal import Decimal

from sidedeck.domain.etoro_demo import DemoPortfolioSnapshot
from sidedeck.domain.etoro_demo_books import (
    BaselinePosition, EtoroDemoBookError, OrderAttribution, baseline_from, book_for_strategy,
)

DDL = (
    "CREATE TABLE IF NOT EXISTS etoro_demo_baseline_capture ("
    "capture_id INTEGER PRIMARY KEY CHECK (capture_id = 1), captured_at TEXT NOT NULL, "
    "snapshot_sha256 TEXT NOT NULL, position_count INTEGER NOT NULL)",
    "CREATE TABLE IF NOT EXISTS etoro_demo_baseline ("
    "position_id INTEGER PRIMARY KEY, instrument_id INTEGER NOT NULL, order_id INTEGER, "
    "is_buy INTEGER NOT NULL, units TEXT NOT NULL, opened_at TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS etoro_demo_order_attribution ("
    "order_id INTEGER PRIMARY KEY, book_id TEXT NOT NULL, recorded_at TEXT NOT NULL, "
    "CHECK (book_id IN ('etoro-demo:tradingagents','etoro-demo:ai-trading')))",
)


def _connect(db_path: str) -> sqlite3.Connection:
    db = sqlite3.connect(db_path, timeout=10, isolation_level=None)
    db.execute("PRAGMA busy_timeout=10000")
    for statement in DDL:
        db.execute(statement)
    return db


class EtoroDemoStore:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        _connect(db_path).close()

    def capture_baseline(self, snapshot: DemoPortfolioSnapshot) -> bool:
        """Record every currently open Demo position as unattributed baseline, once."""
        candidate = baseline_from(snapshot)
        db = _connect(self.db_path)
        try:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM etoro_demo_baseline_capture").fetchone():
                existing = self._baseline(db)
                db.execute("ROLLBACK")
                if existing != candidate:
                    raise EtoroDemoBookError("a different Demo baseline is already recorded")
                return False
            if db.execute("SELECT 1 FROM etoro_demo_order_attribution LIMIT 1").fetchone():
                raise EtoroDemoBookError("baseline must be captured before any SideDeck order")
            db.execute("INSERT INTO etoro_demo_baseline_capture (capture_id, captured_at, "
                       "snapshot_sha256, position_count) VALUES (1, ?, ?, ?)",
                       (snapshot.observed_at.astimezone(timezone.utc).isoformat(),
                        snapshot.payload_sha256, len(candidate)))
            for base in candidate:
                db.execute("INSERT INTO etoro_demo_baseline (position_id, instrument_id, order_id, "
                           "is_buy, units, opened_at) VALUES (?, ?, ?, ?, ?, ?)",
                           (base.position_id, base.instrument_id, base.order_id, int(base.is_buy),
                            str(base.units), base.opened_at.isoformat()))
            db.execute("COMMIT")
            return True
        except BaseException:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        finally:
            db.close()

    @staticmethod
    def _baseline(db: sqlite3.Connection) -> tuple[BaselinePosition, ...]:
        rows = db.execute("SELECT position_id, instrument_id, order_id, is_buy, units, opened_at "
                          "FROM etoro_demo_baseline ORDER BY position_id").fetchall()
        return tuple(BaselinePosition(r[0], r[1], r[2], bool(r[3]), Decimal(r[4]),
                                      datetime.fromisoformat(r[5])) for r in rows)

    def baseline_captured(self) -> bool:
        db = _connect(self.db_path)
        try:
            return db.execute("SELECT 1 FROM etoro_demo_baseline_capture").fetchone() is not None
        finally:
            db.close()

    def baseline(self) -> tuple[BaselinePosition, ...]:
        db = _connect(self.db_path)
        try:
            return self._baseline(db)
        finally:
            db.close()

    def record_order_attribution(self, *, order_id: int, strategy: str, at: datetime) -> None:
        """For the future, separately approved Demo order path only. Immutable once written."""
        if type(order_id) is not int or order_id <= 0:
            raise EtoroDemoBookError("invalid Demo order ID")
        if at.tzinfo is None:
            raise EtoroDemoBookError("attribution time must be timezone-aware")
        book = book_for_strategy(strategy)
        db = _connect(self.db_path)
        try:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM etoro_demo_baseline_capture").fetchone() is None:
                raise EtoroDemoBookError("capture the Demo baseline before attributing orders")
            if db.execute("SELECT 1 FROM etoro_demo_baseline WHERE order_id=?",
                          (order_id,)).fetchone():
                raise EtoroDemoBookError("order belongs to a baseline position")
            row = db.execute("SELECT book_id FROM etoro_demo_order_attribution WHERE order_id=?",
                             (order_id,)).fetchone()
            if row is not None:
                db.execute("ROLLBACK")
                if row[0] != book:
                    raise EtoroDemoBookError("order is already attributed to another strategy")
                return
            db.execute("INSERT INTO etoro_demo_order_attribution (order_id, book_id, recorded_at) "
                       "VALUES (?, ?, ?)", (order_id, book, at.astimezone(timezone.utc).isoformat()))
            db.execute("COMMIT")
        except BaseException:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        finally:
            db.close()

    def attributions(self) -> tuple[OrderAttribution, ...]:
        db = _connect(self.db_path)
        try:
            rows = db.execute("SELECT order_id, book_id FROM etoro_demo_order_attribution "
                              "ORDER BY order_id").fetchall()
        finally:
            db.close()
        return tuple(OrderAttribution(order_id, book) for order_id, book in rows)
