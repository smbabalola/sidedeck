"""SD-079 independent DAY / SWING / POSITION paper ledgers (local simulation only).

Each track owns separate virtual cash, positions, fees and an append-only event
log persisted in SQLite and replayed on load. Fills are ``SIMULATED_LOCAL`` —
never broker fills. Entries require an SD-071 ``ELIGIBLE`` decision for the same
track and an SD-072 risk gate that allows entries. Positions cannot be moved,
closed or funded across tracks; a DAY position is never converted to SWING.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

from sidedeck.application.sd071_decision_engine import Decision
from sidedeck.application.sd072_track_risk_limits import (
    RiskGate,
    TrackLimits,
    TrackRiskState,
    evaluate_track_risk,
)

FILL_BASIS = "SIMULATED_LOCAL"
ZERO = Decimal(0)


class LedgerError(ValueError):
    pass


@dataclass
class Position:
    ref: str
    canonical_id: str
    quantity: Decimal
    entry_price: Decimal
    entry_fee: Decimal
    opened_at: datetime
    decision_policy: str
    signal_ids: tuple[str, ...]
    stop_price: Decimal


@dataclass
class TrackLedger:
    track: str
    initial_capital: Decimal
    path: Path
    cash: Decimal = ZERO
    peak_equity: Decimal = ZERO
    positions: dict[str, Position] = field(default_factory=dict)
    realized_pnl: Decimal = ZERO
    fees: Decimal = ZERO
    entries_by_day: dict[str, int] = field(default_factory=dict)
    closed: list[dict[str, str]] = field(default_factory=list)

    _seq: int = 0

    @classmethod
    def open(cls, path: Path, track: str, initial_capital: Decimal) -> "TrackLedger":
        if not initial_capital.is_finite() or initial_capital <= 0:
            raise LedgerError("initial capital must be positive")
        ledger = cls(track, initial_capital, path, cash=initial_capital,
                     peak_equity=initial_capital)
        with closing(sqlite3.connect(path, isolation_level=None)) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS meta (track TEXT PRIMARY KEY, capital TEXT)")
            conn.execute("CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY, kind TEXT,"
                         " payload TEXT)")
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT track, capital FROM meta").fetchone()
            if row is None:
                conn.execute("INSERT INTO meta VALUES (?, ?)", (track, str(initial_capital)))
            elif row[0] != track or Decimal(row[1]) != initial_capital:
                conn.execute("ROLLBACK")
                raise LedgerError("ledger file belongs to a different track or capital")
            ledger._catch_up(conn)
            conn.execute("COMMIT")
        return ledger

    # --- event sourcing -----------------------------------------------------------
    def _catch_up(self, conn: sqlite3.Connection) -> None:
        """Apply events written by any other instance since this one last looked."""
        rows = conn.execute("SELECT seq, kind, payload FROM events WHERE seq > ? ORDER BY seq",
                            (self._seq,)).fetchall()
        for seq, kind, payload in rows:
            self._apply(kind, json.loads(payload))
            self._seq = int(seq)

    def _mutate(self, build: Callable[[], tuple[str, dict[str, Any]]]) -> None:
        """Lock, catch up, validate against fresh state (``build``), append, apply."""
        with closing(sqlite3.connect(self.path, isolation_level=None)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                self._catch_up(conn)
                kind, payload = build()
                cur = conn.execute("INSERT INTO events (kind, payload) VALUES (?, ?)",
                                   (kind, json.dumps(payload, sort_keys=True)))
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        self._apply(kind, payload)
        self._seq = int(cur.lastrowid or self._seq)

    def refresh(self) -> None:
        with closing(sqlite3.connect(self.path, isolation_level=None)) as conn:
            self._catch_up(conn)

    def _apply(self, kind: str, p: dict[str, Any]) -> None:
        if kind == "OPEN":
            qty, price, fee = Decimal(p["quantity"]), Decimal(p["price"]), Decimal(p["fee"])
            self.cash -= qty * price + fee
            self.fees += fee
            opened = datetime.fromisoformat(p["at"])
            self.positions[p["ref"]] = Position(
                p["ref"], p["canonical_id"], qty, price, fee, opened, p["policy"],
                tuple(p["signal_ids"]), Decimal(p["stop"]))
            day = opened.date().isoformat()
            self.entries_by_day[day] = self.entries_by_day.get(day, 0) + 1
        elif kind == "CLOSE":
            pos = self.positions.pop(p["ref"])
            price, fee = Decimal(p["price"]), Decimal(p["fee"])
            proceeds = pos.quantity * price - fee
            self.cash += proceeds
            self.fees += fee
            pnl = proceeds - (pos.quantity * pos.entry_price + pos.entry_fee)
            self.realized_pnl += pnl
            self.closed.append({"ref": pos.ref, "canonical_id": pos.canonical_id,
                                "pnl": str(pnl), "reason": p["reason"], "at": p["at"]})
        elif kind == "MARK":
            self.peak_equity = max(self.peak_equity, Decimal(p["equity"]))
        else:
            raise LedgerError(f"unknown ledger event {kind}")

    # --- operations ---------------------------------------------------------------
    def equity(self, prices: dict[str, Decimal]) -> Decimal:
        missing = [p.canonical_id for p in self.positions.values() if p.canonical_id not in prices]
        if missing:
            raise LedgerError(f"no mark price for {sorted(missing)}")
        return self.cash + sum((p.quantity * prices[p.canonical_id]
                                for p in self.positions.values()), ZERO)

    def mark(self, prices: dict[str, Decimal], at: datetime) -> Decimal:
        values: list[Decimal] = []

        def build() -> tuple[str, dict[str, Any]]:
            values.append(self.equity(prices))
            return "MARK", {"equity": str(values[0]), "at": at.isoformat()}

        self._mutate(build)
        return values[0]

    def risk_gate(self, limits: TrackLimits, prices: dict[str, Decimal],
                  session_start_equity: Decimal, day: str) -> RiskGate:
        equity = self.equity(prices)
        state = TrackRiskState(self.track, equity, max(self.peak_equity, equity),
                               session_start_equity, self.entries_by_day.get(day, 0))
        return evaluate_track_risk(state, limits)

    def open_from_decision(
        self, ref: str, decision: Decision, fill_price: Decimal, fee: Decimal, at: datetime, *,
        limits: TrackLimits, prices: dict[str, Decimal], session_start_equity: Decimal,
    ) -> Position:
        """Open a simulated position. The risk gate is computed here, inside the write lock,
        from this ledger's freshly replayed state; callers cannot supply a stale gate."""
        if decision.track != self.track or limits.track != self.track:
            raise LedgerError("decision or limits belong to another track")
        if decision.status != "ELIGIBLE" or decision.sizing is None:
            raise LedgerError("only ELIGIBLE decisions can open simulated positions")
        if at.tzinfo is None or at < decision.decided_at:
            raise LedgerError("fill must be timezone-aware and after the decision")
        if not (fill_price.is_finite() and fill_price > 0 and fee.is_finite() and fee >= 0):
            raise LedgerError("invalid fill price or fee")
        sizing = decision.sizing

        def build() -> tuple[str, dict[str, Any]]:
            gate = self.risk_gate(limits, prices, session_start_equity, at.date().isoformat())
            if not gate.entries_allowed:
                raise LedgerError(f"risk gate blocks entries: {gate.reasons}")
            if ref in self.positions or any(c["ref"] == ref for c in self.closed):
                raise LedgerError("duplicate position reference")
            if sizing.quantity * fill_price + fee > self.cash:
                raise LedgerError("insufficient track cash")
            return "OPEN", {
                "ref": ref, "canonical_id": decision.canonical_id,
                "quantity": str(sizing.quantity), "price": str(fill_price), "fee": str(fee),
                "at": at.isoformat(), "policy": decision.policy_id,
                "signal_ids": list(decision.qualified_signal_ids),
                "stop": str(sizing.stop_price), "basis": FILL_BASIS,
            }

        self._mutate(build)
        return self.positions[ref]

    def close(self, ref: str, price: Decimal, fee: Decimal, at: datetime, reason: str) -> Decimal:
        if at.tzinfo is None:
            raise LedgerError("close must be timezone-aware")
        if not (price.is_finite() and price > 0 and fee.is_finite() and fee >= 0):
            raise LedgerError("invalid close price or fee")
        before = self.realized_pnl

        def build() -> tuple[str, dict[str, Any]]:
            pos = self.positions.get(ref)
            if pos is None:
                raise LedgerError("position is not open in this track")
            if at < pos.opened_at:
                raise LedgerError("close must be after the open")
            return "CLOSE", {"ref": ref, "price": str(price), "fee": str(fee),
                             "at": at.isoformat(), "reason": reason[:64], "basis": FILL_BASIS}

        self._mutate(build)
        return self.realized_pnl - before


@dataclass
class TrackBook:
    """Container that keeps the three ledgers strictly separate."""

    ledgers: dict[str, TrackLedger]

    @classmethod
    def open(cls, directory: Path, capital: dict[str, Decimal]) -> "TrackBook":
        if set(capital) - {"DAY", "SWING", "POSITION"}:
            raise LedgerError("unknown track")
        directory.mkdir(parents=True, exist_ok=True)
        return cls({t: TrackLedger.open(directory / f"{t.lower()}-ledger.sqlite3", t, c)
                    for t, c in capital.items()})

    def ledger(self, track: str) -> TrackLedger:
        try:
            return self.ledgers[track]
        except KeyError as exc:
            raise LedgerError(f"no ledger for track {track}") from exc
