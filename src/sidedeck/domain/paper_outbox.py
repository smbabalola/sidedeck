"""Restart-safe, SQLite-backed SideDeck PAPER outbox and strategy journal.

No broker transport, no credentials, and NO submit/cancel write endpoints.
Each local operation rebuilds from committed rows under BEGIN IMMEDIATE.
Order state and ledger postings commit in the same SQLite transaction.
This is a *separate* SideDeck research/paper journal, never a user broker DB.
"""

from __future__ import annotations

from contextlib import closing, contextmanager
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterator
from uuid import UUID

from .accounting import Ledger, opening_event
from .contracts import AUTHORIZED_PORTFOLIOS, LedgerEvent, MarketSnapshot, TradeIntent, require_utc
from .paper_desk import (
    BROKER_KEY_SLOTS, DeskOrderStatus, FillReconciliation, PaperDeskError,
    PaperFillEvidence, PaperOrderDraft, PaperOrderTrack, SideDeckPaperDesk,
)

# Application identifier prevents opening or migrating unrelated user databases.
_APP_ID = 0x53444543
_VERSION = 1
_TERMINAL = {DeskOrderStatus.FILLED, DeskOrderStatus.CANCELLED}


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _draft_load(value: str) -> PaperOrderDraft:
    obj = json.loads(value)
    if not isinstance(obj, dict):
        raise PaperDeskError("invalid stored paper draft")
    obj["local_order_id"] = UUID(obj["local_order_id"])
    obj["created_at"] = datetime.fromisoformat(obj["created_at"])
    obj["quantity"] = Decimal(obj["quantity"])
    obj["limit_price"] = Decimal(obj["limit_price"])
    draft = PaperOrderDraft(**obj)
    if (
        draft.portfolio_id not in BROKER_KEY_SLOTS
        or draft.key_slot != BROKER_KEY_SLOTS[draft.portfolio_id]
        or draft.quantity <= 0 or not draft.quantity.is_finite()
        or draft.limit_price <= 0 or not draft.limit_price.is_finite()
        or draft.submission_enabled
        or draft.side not in ("buy", "sell")
        or require_utc(draft.created_at) != draft.created_at
    ):
        raise PaperDeskError("invalid persisted strategy draft")
    return draft


def _fill_load(value: str) -> PaperFillEvidence:
    obj = json.loads(value)
    if not isinstance(obj, dict):
        raise PaperDeskError("invalid stored fill evidence")
    obj["quantity"] = Decimal(obj["quantity"])
    obj["price"] = Decimal(obj["price"])
    obj["fee"] = Decimal(obj["fee"])
    obj["occurred_at"] = datetime.fromisoformat(obj["occurred_at"])
    return PaperFillEvidence(**obj)


class DurablePaperDesk:
    """Local journal/outbox with no broker networking.

    The only permissible new DB is the caller's deliberately chosen file.
    Existing SQLite files without SideDeck's marker fail CLOSED.
    """

    def __init__(self, db_path: Path) -> None:
        self.path = db_path
        if self.path.suffix != ".sqlite3":
            raise PaperDeskError("SideDeck PAPER DB requires a dedicated .sqlite3 filename")
        if self.path.exists():
            if not self.path.is_file():
                raise PaperDeskError("paper journal target is not a file")
            # Read-only check first: never overwrite an unrelated SQLite file.
            with closing(sqlite3.connect(f"file:{self.path.resolve().as_posix()}?mode=ro", uri=True)) as db:
                if db.execute("PRAGMA application_id").fetchone()[0] != _APP_ID:
                    raise PaperDeskError("existing database is not a SideDeck paper journal")
                if db.execute("PRAGMA user_version").fetchone()[0] != _VERSION:
                    raise PaperDeskError("incompatible SideDeck PAPER journal version")
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._transaction() as db:
            app_id = db.execute("PRAGMA application_id").fetchone()[0]
            if app_id == 0:
                db.execute(f"PRAGMA application_id = {_APP_ID}")
                db.execute(f"PRAGMA user_version = {_VERSION}")
            elif app_id != _APP_ID:
                raise PaperDeskError("unrelated database")
            # sqlite3.executescript() implicitly commits, so individual DDL
            # statements preserve the caller's BEGIN IMMEDIATE transaction.
            db.execute(
                "CREATE TABLE IF NOT EXISTS paper_orders("
                "client_order_id TEXT PRIMARY KEY, portfolio_id TEXT NOT NULL,"
                "draft_json TEXT NOT NULL, state TEXT NOT NULL,"
                "broker_order_id TEXT, filled_quantity TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS paper_fills("
                "broker_fill_id TEXT PRIMARY KEY,"
                "client_order_id TEXT NOT NULL REFERENCES paper_orders(client_order_id),"
                "evidence_json TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS paper_events("
                "sequence INTEGER PRIMARY KEY AUTOINCREMENT,"
                "portfolio_id TEXT NOT NULL, idempotency_key TEXT NOT NULL,"
                "payload_json TEXT NOT NULL, UNIQUE(portfolio_id,idempotency_key))"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS paper_controls("
                "name TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            db.execute(
                "INSERT OR IGNORE INTO paper_controls(name,value) VALUES('kill_switch','ENGAGED')"
            )

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        try:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.execute("COMMIT")
            except BaseException:
                if db.in_transaction:
                    db.execute("ROLLBACK")
                raise
        finally:
            db.close()

    @property
    def paper_write_enabled(self) -> bool:
        return False

    @property
    def kill_switch_engaged(self) -> bool:
        with self._transaction() as db:
            control = db.execute(
                "SELECT value FROM paper_controls WHERE name='kill_switch'"
            ).fetchone()
            if control != ("ENGAGED",):
                raise PaperDeskError("PAPER kill switch is not engaged")
        return True

    def initialize(self, *, opened_at: datetime) -> None:
        """Open both USD 1000 ledgers once. Does not touch broker accounts."""
        opened_at = require_utc(opened_at)
        with self._transaction() as db:
            ledger, _ = self._restore(db)
            if ledger.events:
                if len([e for e in ledger.events if e.event_type.value == "OPENING_CAPITAL"]) != 2:
                    raise PaperDeskError("paper journal is missing an opening portfolio")
                return
            for pid in AUTHORIZED_PORTFOLIOS:
                event = opening_event(pid, opened_at)
                ledger.append(event)
                self._insert_event(db, event)

    def _restore(self, db: sqlite3.Connection) -> tuple[Ledger, SideDeckPaperDesk]:
        """Rebuild from committed journal each operation; fail on corruption."""
        switch = db.execute(
            "SELECT value FROM paper_controls WHERE name='kill_switch'"
        ).fetchone()
        if switch != ("ENGAGED",):
            raise PaperDeskError("paper kill switch is not engaged")
        ledger = Ledger()
        for (raw,) in db.execute(
            "SELECT payload_json FROM paper_events ORDER BY sequence"
        ):
            ledger.append(LedgerEvent.model_validate_json(raw))
        desk = SideDeckPaperDesk()
        for (order_id, pid, raw, state, broker_id, filled_qty) in db.execute(
            "SELECT client_order_id,portfolio_id,draft_json,state,"
            "broker_order_id,filled_quantity FROM paper_orders ORDER BY rowid"
        ):
            draft = _draft_load(raw)
            if draft.client_order_id != order_id or draft.portfolio_id != pid:
                raise PaperDeskError("persisted paper order identity mismatch")
            status = DeskOrderStatus(state)
            track = PaperOrderTrack(
                draft=draft, status=status, broker_order_id=broker_id,
                filled_quantity=Decimal(filled_qty),
            )
            if track.filled_quantity < 0 or not track.filled_quantity.is_finite():
                raise PaperDeskError("invalid persisted fill total")
            desk._orders[order_id] = track
            if status not in _TERMINAL:
                if pid in desk._active_by_portfolio:
                    raise PaperDeskError("multiple pending paper orders for one strategy")
                desk._active_by_portfolio[pid] = order_id
        for (raw_id, order_id, evidence_json) in db.execute(
            "SELECT broker_fill_id,client_order_id,evidence_json "
            "FROM paper_fills ORDER BY rowid"
        ):
            found = desk._orders.get(order_id)
            if found is None:
                raise PaperDeskError("orphan paper fill evidence")
            evidence = _fill_load(evidence_json)
            if (
                evidence.broker_fill_id != raw_id
                or evidence.client_order_id != order_id
                or evidence.portfolio_id != found.draft.portfolio_id
                or evidence.key_slot != found.draft.key_slot
            ):
                raise PaperDeskError("persisted fill crosses strategy identity")
            found.evidence_by_fill_id[raw_id] = evidence
        for track in desk._orders.values():
            total = sum((f.quantity for f in track.evidence_by_fill_id.values()), Decimal("0"))
            if total != track.filled_quantity or total > track.draft.quantity:
                raise PaperDeskError("paper outbox quantity differs from accepted fills")
            if track.status is DeskOrderStatus.FILLED and total != track.draft.quantity:
                raise PaperDeskError("filled paper order has incomplete quantity")
            if total > 0 and track.broker_order_id is None:
                raise PaperDeskError("fill lacks broker acknowledgment")
        return ledger, desk

    @staticmethod
    def _insert_event(db: sqlite3.Connection, event: LedgerEvent) -> None:
        db.execute(
            "INSERT INTO paper_events(portfolio_id,idempotency_key,payload_json) "
            "VALUES (?,?,?)",
            (event.portfolio_id, event.idempotency_key, event.model_dump_json()),
        )

    def prepare(
        self, intent: TradeIntent, snapshot: MarketSnapshot,
        *, marks: dict[str, MarketSnapshot],
    ) -> PaperOrderDraft:
        with self._transaction() as db:
            ledger, desk = self._restore(db)
            if len(ledger.events) < 2:
                raise PaperDeskError("initialize both separate paper ledgers first")
            existing = len(desk._orders)
            draft, _ = desk.prepare(
                intent, ledger.replay(intent.portfolio_id), snapshot, marks=marks,
            )
            if len(desk._orders) != existing:
                db.execute(
                    "INSERT INTO paper_orders VALUES(?,?,?,?,?,?)",
                    (draft.client_order_id, draft.portfolio_id, _json(asdict(draft)),
                     DeskOrderStatus.PREPARED.value, None, "0"),
                )
            return draft

    def acknowledge(self, client_order_id: str, *, broker_order_id: str) -> None:
        """Record offline broker acknowledgment; never performs GET or POST."""
        with self._transaction() as db:
            _, desk = self._restore(db)
            desk.acknowledge(client_order_id, broker_order_id=broker_order_id)
            db.execute(
                "UPDATE paper_orders SET state=?, broker_order_id=? "
                "WHERE client_order_id=?",
                (desk._track(client_order_id).status.value, broker_order_id, client_order_id),
            )

    def reconcile_fill(self, evidence: PaperFillEvidence) -> FillReconciliation:
        """Commit both local order state and journal event atomically.

        No broker confirmation occurs in this method: caller must supply
        independently authenticated/fresh paper execution evidence later.
        """
        with self._transaction() as db:
            ledger, desk = self._restore(db)
            before = len(ledger.events)
            result = desk.reconcile_fill(evidence, ledger)
            if not result.applied:
                return result
            if len(ledger.events) != before + 1:
                raise PaperDeskError("paper fill lacks exactly one ledger posting")
            self._insert_event(db, ledger.events[-1])
            db.execute(
                "INSERT INTO paper_fills VALUES(?,?,?)",
                (evidence.broker_fill_id, evidence.client_order_id, _json(asdict(evidence))),
            )
            db.execute(
                "UPDATE paper_orders SET state=?,filled_quantity=? WHERE client_order_id=?",
                (result.order_status.value, str(result.cumulative_quantity), evidence.client_order_id),
            )
            return result

    def order_binding(
        self, client_order_id: str,
    ) -> tuple[PaperOrderDraft, str | None]:
        """Read a locally prepared order and broker acknowledgment identity."""
        with self._transaction() as db:
            _, desk = self._restore(db)
            record = desk._track(client_order_id)
            return record.draft, record.broker_order_id

    def order_draft(self, client_order_id: str) -> PaperOrderDraft:
        """Read an accepted local order by id; no broker I/O or journal edits."""
        draft, _ = self.order_binding(client_order_id)
        return draft

    def snapshot(self) -> dict[str, Any]:
        """Safe local order/ledger state, excluding broker account IDs and keys."""
        with self._transaction() as db:
            ledger, desk = self._restore(db)
            result: dict[str, Any] = {
                "mode": "LOCAL_PAPER_JOURNAL_OFFLINE",
                "kill_switch_engaged": True,
                "broker_writes_enabled": False,
                "strategies": {},
            }
            for pid in AUTHORIZED_PORTFOLIOS:
                state = ledger.replay(pid)
                result["strategies"][pid] = {
                    "key_slot": BROKER_KEY_SLOTS[pid],
                    "cash": str(state.cash),
                    "positions": {
                        iid: str(pos.quantity)
                        for iid, pos in state.positions.items()
                    },
                    "orders": [
                        {
                            "client_order_id": track.draft.client_order_id,
                            "symbol": track.draft.symbol,
                            "side": track.draft.side,
                            "state": track.status.value,
                            "filled_quantity": str(track.filled_quantity),
                        }
                        for track in desk._orders.values()
                        if track.draft.portfolio_id == pid
                    ],
                }
            return result
