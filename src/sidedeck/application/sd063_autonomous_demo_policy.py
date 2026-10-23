"""SD-063 bounded autonomous eToro Demo policy (offline design; proposals only).

A policy is a canonical JSON document the **owner** reviews and, in a separate step, releases
by signing an SD-064 ``autonomous_policy`` grant whose ``subject_digest`` is this policy's
digest. This module never signs, never unlocks the order transport and never sends anything:
it turns ELIGIBLE SD-071 decisions into bounded, single-use entry proposals and manages exits
for lineage-verified positions. Every proposal is marked ``OFFLINE_PROPOSAL_NOT_SUBMITTED``.

Rules (all fail closed):

* **Scope:** eToro Demo only (Real permanently excluded), owner principal only, window
  <= 7 days (the SD-064 maximum), SWING/POSITION tracks only (DAY stays BLOCKED_EXTERNAL
  without approved intraday data), total virtual capital <= USD 1000, explicit instrument
  mappings, the protected baseline instruments can never be in scope or managed.
* **Strategy admission:** every qualified signal behind a decision must come from a
  ``NATIVE_STRATEGY`` that is both named in the policy and ADMITTED (SD-071) with the same
  evidence reference. Agent agreement never qualifies.
* **Risk:** SD-072 drawdown, daily-loss and order-frequency gates per track; per-day entry
  cap; max open positions; per-position notional cap (units are shrunk, never grown);
  long-only, 1x, limit IOC at most ``ask x (1 + premium)`` on a quote <= 60 s old, inside
  the exchange session.
* **Recovery:** one unresolved entry per track at a time; each decision is single-use; an
  ``UNRESOLVED`` outcome trips a persistent kill-switch that blocks entries and exits.
* **Audit:** an append-only SQLite ledger (UPDATE/DELETE refused by triggers) bound to one
  policy digest records proposals, outcomes, alerts and kill-switch trips.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_DOWN, Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping, Sequence

from sidedeck.application.sd064_unlock_grant import UnlockGrant
from sidedeck.application.sd068_track_scheduler import NEW_YORK, SchedulerError, session_for
from sidedeck.application.sd070_research_signal import ResearchSignal
from sidedeck.application.sd071_decision_engine import Decision, StrategyAdmission
from sidedeck.application.sd072_track_risk_limits import (
    TrackLimits, TrackRiskState, evaluate_track_risk,
)

SCHEMA = "sidedeck-autonomous-demo-policy/1"
BROKER = "etoro-demo"
OWNER_PRINCIPAL = "owner@sidedeck"
AUTONOMOUS_TRACKS = ("SWING", "POSITION")
MAX_POLICY_WINDOW = timedelta(days=7)
MAX_TOTAL_CAPITAL = Decimal("1000")
MAX_LIMIT_PREMIUM = Decimal("0.005")
MAX_QUOTE_AGE_SECONDS = 60
MAX_DECISION_AGE_SECONDS = 900
MAX_ORDERS_PER_DAY = 20
EXPIRY_FLATTEN_WINDOW = timedelta(days=1)
SUBMISSION = "OFFLINE_PROPOSAL_NOT_SUBMITTED"
OUTCOMES = ("FILLED", "PARTIALLY_FILLED", "NOT_FILLED", "UNRESOLVED")
_HEX64 = re.compile(r"[0-9a-f]{64}")
_FIELDS = {"schema", "policy_id", "broker", "issued_by", "not_before", "expires_at", "tracks",
           "strategies", "instruments", "protected_instrument_ids", "max_limit_premium_pct",
           "max_quote_age_seconds", "max_decision_age_seconds", "purpose"}
_LEDGER_TABLES = {"meta", "events", "sqlite_sequence"}
_TRACK_FIELDS = {"track", "virtual_capital", "max_position_notional", "max_open_positions",
                 "max_new_entries_per_day", "max_orders_per_day", "max_daily_loss_pct",
                 "max_drawdown_pct"}


class PolicyRefused(PermissionError):
    pass


def _is_int(value: Any) -> bool:
    return type(value) is int


def _decimal(value: Any, name: str) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise PolicyRefused(f"{name} must be a finite Decimal")
    return value


@dataclass(frozen=True)
class TrackBudget:
    track: str
    virtual_capital: Decimal
    max_position_notional: Decimal
    max_open_positions: int
    max_new_entries_per_day: int
    max_orders_per_day: int
    max_daily_loss_pct: Decimal
    max_drawdown_pct: Decimal


@dataclass(frozen=True)
class StrategyScope:
    strategy_id: str
    version: str
    track: str
    evidence_ref: str


@dataclass(frozen=True)
class InstrumentScope:
    canonical_id: str
    etoro_instrument_id: int


@dataclass(frozen=True)
class AutonomousDemoPolicy:
    policy_id: str
    not_before: datetime
    expires_at: datetime
    tracks: tuple[TrackBudget, ...]
    strategies: tuple[StrategyScope, ...]
    instruments: tuple[InstrumentScope, ...]
    protected_instrument_ids: frozenset[int]
    max_limit_premium_pct: Decimal
    max_quote_age_seconds: int
    max_decision_age_seconds: int
    purpose: str
    broker: str = BROKER
    issued_by: str = OWNER_PRINCIPAL

    def __post_init__(self) -> None:
        if self.broker != BROKER:
            raise PolicyRefused("only eToro Demo is in scope; Real is permanently excluded")
        if self.issued_by != OWNER_PRINCIPAL:
            raise PolicyRefused("a policy can only be issued for the owner principal")
        try:
            canonical_id = str(uuid.UUID(str(self.policy_id)))
        except ValueError:
            raise PolicyRefused("policy_id must be a canonical UUID") from None
        if canonical_id != self.policy_id:
            raise PolicyRefused("policy_id must be a canonical lowercase UUID")
        if self.not_before.tzinfo is None or self.expires_at.tzinfo is None:
            raise PolicyRefused("policy timestamps must be timezone-aware")
        window = self.expires_at - self.not_before
        if window <= timedelta(0):
            raise PolicyRefused("policy window must be positive")
        if window > MAX_POLICY_WINDOW:
            raise PolicyRefused("policy window must be at most 7 days")
        self._check_tracks()
        self._check_strategies()
        self._check_instruments()
        premium = _decimal(self.max_limit_premium_pct, "max_limit_premium_pct")
        if not Decimal(0) < premium <= MAX_LIMIT_PREMIUM:
            raise PolicyRefused("limit premium must be in (0, 0.005]")
        if not _is_int(self.max_quote_age_seconds) or \
                not 0 < self.max_quote_age_seconds <= MAX_QUOTE_AGE_SECONDS:
            raise PolicyRefused("max quote age must be 1-60 seconds")
        if not _is_int(self.max_decision_age_seconds) or \
                not 0 < self.max_decision_age_seconds <= MAX_DECISION_AGE_SECONDS:
            raise PolicyRefused("max decision age must be 1-900 seconds")
        if not isinstance(self.purpose, str) or not 0 < len(self.purpose) <= 500:
            raise PolicyRefused("purpose must be 1-500 characters")

    def _check_tracks(self) -> None:
        if not self.tracks:
            raise PolicyRefused("a policy needs at least one track")
        names = [b.track for b in self.tracks]
        if len(set(names)) != len(names):
            raise PolicyRefused("duplicate track budget")
        total = Decimal(0)
        for b in self.tracks:
            if b.track == "DAY":
                raise PolicyRefused("DAY track is BLOCKED_EXTERNAL without approved intraday data")
            if b.track not in AUTONOMOUS_TRACKS:
                raise PolicyRefused(f"unknown track {b.track}")
            capital = _decimal(b.virtual_capital, "virtual_capital")
            notional = _decimal(b.max_position_notional, "max_position_notional")
            if capital <= 0:
                raise PolicyRefused("virtual capital must be positive")
            if not Decimal(0) < notional <= capital:
                raise PolicyRefused("max position notional must be within the track capital")
            for name in ("max_open_positions", "max_new_entries_per_day", "max_orders_per_day"):
                value = getattr(b, name)
                if not _is_int(value) or value <= 0:
                    raise PolicyRefused(f"{name} must be a positive integer")
            if notional * b.max_open_positions > capital:
                raise PolicyRefused("max position notional x max open positions exceeds the "
                                    "track capital")
            if b.max_orders_per_day > MAX_ORDERS_PER_DAY:
                raise PolicyRefused(f"max_orders_per_day must be <= {MAX_ORDERS_PER_DAY}")
            if b.max_new_entries_per_day > b.max_orders_per_day:
                raise PolicyRefused("new entries per day cannot exceed orders per day")
            for name in ("max_daily_loss_pct", "max_drawdown_pct"):
                if not Decimal(0) < _decimal(getattr(b, name), name) < 1:
                    raise PolicyRefused("loss limits must be in (0, 1)")
            total += capital
        if total > MAX_TOTAL_CAPITAL:
            raise PolicyRefused("total virtual capital exceeds the USD 1000 ceiling")

    def _check_strategies(self) -> None:
        if not self.strategies:
            raise PolicyRefused("a policy needs at least one strategy")
        tracks = {b.track for b in self.tracks}
        keys = [(s.strategy_id, s.version, s.track) for s in self.strategies]
        if len(set(keys)) != len(keys):
            raise PolicyRefused("duplicate strategy scope")
        for s in self.strategies:
            if not all(isinstance(v, str) and v.strip()
                       for v in (s.strategy_id, s.version, s.evidence_ref)):
                raise PolicyRefused("strategy scope needs id, version and evidence reference")
            if s.track not in tracks:
                raise PolicyRefused("strategy track is not a policy track")

    def _check_instruments(self) -> None:
        if not self.instruments:
            raise PolicyRefused("a policy needs at least one instrument")
        if not isinstance(self.protected_instrument_ids, frozenset) or not all(
                _is_int(i) for i in self.protected_instrument_ids):
            raise PolicyRefused("protected instrument ids must be a frozenset of integers")
        ids = [i.etoro_instrument_id for i in self.instruments]
        cids = [i.canonical_id for i in self.instruments]
        if len(set(ids)) != len(ids) or len(set(cids)) != len(cids):
            raise PolicyRefused("duplicate instrument mapping")
        for item in self.instruments:
            if not _is_int(item.etoro_instrument_id) or item.etoro_instrument_id <= 0:
                raise PolicyRefused("eToro instrument id must be a positive integer")
            if not isinstance(item.canonical_id, str) or ":" not in item.canonical_id:
                raise PolicyRefused("canonical instrument id required")
            if item.etoro_instrument_id in self.protected_instrument_ids:
                raise PolicyRefused("instrument is in the protected baseline")

    def budget(self, track: str) -> TrackBudget | None:
        return next((b for b in self.tracks if b.track == track), None)

    def instrument(self, canonical_id: str) -> InstrumentScope | None:
        return next((i for i in self.instruments if i.canonical_id == canonical_id), None)

    def active(self, now: datetime) -> bool:
        return self.not_before <= now < self.expires_at

    def to_document(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA, "policy_id": self.policy_id, "broker": self.broker,
            "issued_by": self.issued_by,
            "not_before": self.not_before.astimezone(timezone.utc).isoformat(),
            "expires_at": self.expires_at.astimezone(timezone.utc).isoformat(),
            "tracks": [{"track": b.track, "virtual_capital": str(b.virtual_capital),
                        "max_position_notional": str(b.max_position_notional),
                        "max_open_positions": b.max_open_positions,
                        "max_new_entries_per_day": b.max_new_entries_per_day,
                        "max_orders_per_day": b.max_orders_per_day,
                        "max_daily_loss_pct": str(b.max_daily_loss_pct),
                        "max_drawdown_pct": str(b.max_drawdown_pct)}
                       for b in sorted(self.tracks, key=lambda b: b.track)],
            "strategies": [[s.strategy_id, s.version, s.track, s.evidence_ref]
                           for s in sorted(self.strategies,
                                           key=lambda s: (s.strategy_id, s.version, s.track))],
            "instruments": [[i.canonical_id, i.etoro_instrument_id]
                            for i in sorted(self.instruments, key=lambda i: i.canonical_id)],
            "protected_instrument_ids": sorted(self.protected_instrument_ids),
            "max_limit_premium_pct": str(self.max_limit_premium_pct),
            "max_quote_age_seconds": self.max_quote_age_seconds,
            "max_decision_age_seconds": self.max_decision_age_seconds,
            "purpose": self.purpose,
        }

    def canonical(self) -> bytes:
        return json.dumps(self.to_document(), sort_keys=True,
                          separators=(",", ":")).encode("utf-8")

    def digest(self) -> str:
        """The SD-064 ``autonomous_policy`` grant's ``subject_digest``."""
        return hashlib.sha256(self.canonical()).hexdigest()

    @classmethod
    def from_document(cls, document: Any) -> "AutonomousDemoPolicy":
        if not isinstance(document, dict) or set(document) != _FIELDS:
            raise PolicyRefused("policy must contain exactly the schema fields")
        if document["schema"] != SCHEMA:
            raise PolicyRefused("unknown policy schema")
        try:
            tracks = []
            for t in document["tracks"]:
                if not isinstance(t, dict) or set(t) != _TRACK_FIELDS:
                    raise PolicyRefused("track budget must contain exactly the schema fields")
                tracks.append(TrackBudget(
                    t["track"], Decimal(t["virtual_capital"]), Decimal(t["max_position_notional"]),
                    t["max_open_positions"], t["max_new_entries_per_day"], t["max_orders_per_day"],
                    Decimal(t["max_daily_loss_pct"]), Decimal(t["max_drawdown_pct"])))
            return cls(
                policy_id=document["policy_id"],
                not_before=datetime.fromisoformat(document["not_before"]),
                expires_at=datetime.fromisoformat(document["expires_at"]),
                tracks=tuple(tracks),
                strategies=tuple(StrategyScope(*s) for s in document["strategies"]),
                instruments=tuple(InstrumentScope(*i) for i in document["instruments"]),
                protected_instrument_ids=frozenset(document["protected_instrument_ids"]),
                max_limit_premium_pct=Decimal(document["max_limit_premium_pct"]),
                max_quote_age_seconds=document["max_quote_age_seconds"],
                max_decision_age_seconds=document["max_decision_age_seconds"],
                purpose=document["purpose"], broker=document["broker"],
                issued_by=document["issued_by"])
        except (TypeError, ValueError, InvalidOperation) as exc:
            if isinstance(exc, PolicyRefused):
                raise
            raise PolicyRefused(f"malformed policy: {type(exc).__name__}") from None


def check_grant_binding(policy: AutonomousDemoPolicy, grant: UnlockGrant, now: datetime) -> None:
    """The signed SD-064 grant must name exactly this policy and sit inside its window.

    Signature verification, caps and revocation stay with ``UnlockAuthority``; this only
    binds an already-verified grant to the policy it releases.
    """
    if grant.broker != BROKER:
        raise PolicyRefused("only eToro Demo grants can release a policy")
    if grant.kind != "autonomous_policy":
        raise PolicyRefused("grant kind must be autonomous_policy")
    if grant.subject_digest != policy.digest():
        raise PolicyRefused("grant subject digest does not match this policy")
    # Equal windows: a shorter grant would end before the pre-expiry flatten and strand
    # positions without an authorized close.
    if (grant.not_before, grant.expires_at) != (policy.not_before, policy.expires_at):
        raise PolicyRefused("grant window must equal the policy window")
    if not (policy.active(now) and grant.not_before <= now < grant.expires_at):
        raise PolicyRefused("grant and policy must both be active now")


class PolicyLedger:
    """Append-only audit ledger for one policy digest."""

    def __init__(self, conn: sqlite3.Connection, policy_digest: str) -> None:
        self._conn = conn
        self.policy_digest = policy_digest

    @classmethod
    def open(cls, path: Path, policy_digest: str) -> "PolicyLedger":
        if not isinstance(policy_digest, str) or not _HEX64.fullmatch(policy_digest):
            raise PolicyRefused("policy digest must be one 64-hex digest")
        conn = sqlite3.connect(str(path))
        try:
            foreign = {name for (name,) in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'")} - _LEDGER_TABLES
            if foreign:
                raise PolicyRefused("refusing a SQLite file that is not an SD-063 policy ledger")
            with conn:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS meta (policy_digest TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS events (
                        seq INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL,
                        event TEXT NOT NULL, track TEXT, reference TEXT,
                        session_date TEXT, detail TEXT);
                    CREATE UNIQUE INDEX IF NOT EXISTS events_single_use
                        ON events(event, reference) WHERE reference IS NOT NULL;
                    CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
                        BEGIN SELECT RAISE(ABORT, 'append-only ledger'); END;
                    CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
                        BEGIN SELECT RAISE(ABORT, 'append-only ledger'); END;
                    CREATE TRIGGER IF NOT EXISTS meta_no_update BEFORE UPDATE ON meta
                        BEGIN SELECT RAISE(ABORT, 'policy binding is immutable'); END;
                    CREATE TRIGGER IF NOT EXISTS meta_no_delete BEFORE DELETE ON meta
                        BEGIN SELECT RAISE(ABORT, 'policy binding is immutable'); END;
                """)
                rows = conn.execute("SELECT policy_digest FROM meta").fetchall()
                if not rows:
                    conn.execute("INSERT INTO meta VALUES (?)", (policy_digest,))
                elif rows != [(policy_digest,)]:
                    raise PolicyRefused("ledger belongs to a different policy")
        except BaseException:
            conn.close()
            raise
        return cls(conn, policy_digest)

    def close(self) -> None:
        self._conn.close()

    def _append(self, at: datetime, event: str, *, track: str | None = None,
                reference: str | None = None, session_date: date | None = None,
                detail: str = "") -> None:
        self._conn.execute(
            "INSERT INTO events (at, event, track, reference, session_date, detail) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (at.astimezone(timezone.utc).isoformat(), event, track, reference,
             session_date.isoformat() if session_date else None, detail))

    def _count(self, sql: str, *args: Any) -> int:
        return int(self._conn.execute(sql, args).fetchone()[0])

    def kill_switch_engaged(self) -> bool:
        return self._count("SELECT COUNT(*) FROM events WHERE event = 'KILL_SWITCH'") > 0

    def trip_kill_switch(self, reason: str, at: datetime) -> None:
        with self._conn:
            self._append(at, "KILL_SWITCH", detail=reason[:200])

    def alert(self, code: str, at: datetime) -> None:
        with self._conn:
            self._append(at, "ALERT", detail=code[:200])

    def has_entry(self, reference: str) -> bool:
        return self._count("SELECT COUNT(*) FROM events WHERE event = 'ENTRY_PROPOSED' "
                           "AND reference = ?", reference) > 0

    def _pending(self, kind: str, track: str | None = None) -> tuple[str, ...]:
        sql = (f"SELECT reference FROM events p WHERE event = '{kind}_PROPOSED' "
               f"AND NOT EXISTS (SELECT 1 FROM events r WHERE r.event = '{kind}_RESOLVED' "
               "AND r.reference = p.reference)")
        args: tuple[Any, ...] = ()
        if track is not None:
            sql += " AND track = ?"
            args = (track,)
        return tuple(r[0] for r in self._conn.execute(sql + " ORDER BY seq", args))

    def pending_entries(self, track: str) -> tuple[str, ...]:
        return self._pending("ENTRY", track)

    def pending_exits(self) -> tuple[str, ...]:
        return self._pending("EXIT")

    def pending_exit_for(self, entry_reference: str) -> bool:
        return any(self._count("SELECT COUNT(*) FROM events WHERE event = 'EXIT_PROPOSED' "
                               "AND reference = ? AND detail = ?", ref, entry_reference)
                   for ref in self.pending_exits())

    def exits_proposed_for(self, entry_reference: str) -> int:
        return self._count("SELECT COUNT(*) FROM events WHERE event = 'EXIT_PROPOSED' "
                           "AND detail = ?", entry_reference)

    def entries_on(self, track: str, day: date) -> int:
        return self._count("SELECT COUNT(*) FROM events WHERE event = 'ENTRY_PROPOSED' "
                           "AND track = ? AND session_date = ?", track, day.isoformat())

    def orders_on(self, track: str, day: date) -> int:
        return self._count("SELECT COUNT(*) FROM events WHERE event IN "
                           "('ENTRY_PROPOSED', 'EXIT_PROPOSED') AND track = ? "
                           "AND session_date = ?", track, day.isoformat())

    def record_proposal(self, kind: str, reference: str, track: str, day: date, at: datetime,
                        detail: str) -> None:
        with self._conn:
            self._append(at, f"{kind}_PROPOSED", track=track, reference=reference,
                         session_date=day, detail=detail)

    def resolve(self, reference: str, outcome: str, at: datetime) -> None:
        """Record the reconciled outcome; UNRESOLVED trips the persistent kill-switch."""
        for kind in ("ENTRY", "EXIT"):
            if reference in self._pending(kind):
                break
        else:
            resolved = self._count("SELECT COUNT(*) FROM events WHERE reference = ? AND event "
                                   "IN ('ENTRY_RESOLVED', 'EXIT_RESOLVED')", reference)
            raise PolicyRefused("proposal already resolved" if resolved
                                else "unknown proposal reference")
        if outcome not in OUTCOMES:
            raise PolicyRefused(f"invalid outcome; expected one of {OUTCOMES}")
        with self._conn:
            self._append(at, f"{kind}_RESOLVED", reference=reference, detail=outcome)
            if outcome == "UNRESOLVED":
                self._append(at, "KILL_SWITCH", detail=f"UNRESOLVED_{kind}:{reference}")


@dataclass(frozen=True)
class EntryQuote:
    canonical_id: str
    ask: Decimal
    quote_time: datetime


@dataclass(frozen=True)
class ExitQuote:
    canonical_id: str
    bid: Decimal
    quote_time: datetime


@dataclass(frozen=True)
class TrackEquity:
    equity: Decimal
    peak_equity: Decimal
    session_start_equity: Decimal


@dataclass(frozen=True)
class ManagedPosition:
    """A position SideDeck opened under this policy (verified order->position lineage)."""
    entry_reference: str
    track: str
    canonical_id: str
    etoro_instrument_id: int
    units: Decimal
    stop_price: Decimal
    horizon_max_days: int
    opened_at: datetime
    lineage_verified: bool


@dataclass(frozen=True)
class Refusal:
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class EntryProposal:
    reference_id: str
    policy_digest: str
    track: str
    canonical_id: str
    etoro_instrument_id: int
    units: Decimal
    limit_price: Decimal
    stop_price: Decimal
    horizon_max_days: int
    strategies: tuple[str, ...]
    decided_at: datetime
    proposed_at: datetime
    direction: str = "BUY"
    order_type: str = "limitIOC"
    leverage: int = 1
    submission: str = SUBMISSION


@dataclass(frozen=True)
class ExitProposal:
    reference_id: str
    entry_reference: str
    policy_digest: str
    track: str
    canonical_id: str
    etoro_instrument_id: int
    units: Decimal
    reason: str
    proposed_at: datetime
    submission: str = SUBMISSION


@dataclass(frozen=True)
class ExitPlan:
    exits: tuple[ExitProposal, ...]
    alerts: tuple[str, ...]


def _session_open(now: datetime) -> bool | None:
    """True/False inside/outside the XNYS session; None when the calendar does not cover."""
    try:
        session = session_for(now.astimezone(NEW_YORK).date())
    except SchedulerError:
        return None
    return session is not None and session.open_utc <= now < session.close_utc


def _fresh(quote_time: datetime, now: datetime, max_age_seconds: int) -> bool:
    return (quote_time.tzinfo is not None and quote_time <= now
            and now - quote_time <= timedelta(seconds=max_age_seconds))


def _entry_reference(policy_digest: str, decision: Decision) -> str:
    payload = "|".join((policy_digest, decision.canonical_id, decision.track,
                        decision.decided_at.astimezone(timezone.utc).isoformat(),
                        *sorted(decision.qualified_signal_ids)))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def propose_entry(
    policy: AutonomousDemoPolicy, ledger: PolicyLedger, *, decision: Decision,
    signals: Sequence[ResearchSignal], admissions: Sequence[StrategyAdmission],
    quote: EntryQuote, equity: TrackEquity, open_positions: Sequence[ManagedPosition],
    now: datetime,
) -> EntryProposal | Refusal:
    """Turn one ELIGIBLE decision into a bounded, single-use, unsent entry proposal."""
    if now.tzinfo is None:
        raise PolicyRefused("timezone-aware time required")
    if ledger.policy_digest != policy.digest():
        raise PolicyRefused("ledger belongs to a different policy")
    if ledger.kill_switch_engaged():
        return Refusal(("KILL_SWITCH_ENGAGED",))
    if not policy.active(now):
        return Refusal(("POLICY_NOT_ACTIVE",))
    if decision.status != "ELIGIBLE" or decision.sizing is None:
        return Refusal(("DECISION_NOT_ELIGIBLE",))
    if decision.decided_at > now or \
            now - decision.decided_at > timedelta(seconds=policy.max_decision_age_seconds):
        return Refusal(("DECISION_STALE",))
    budget = policy.budget(decision.track)
    if budget is None:
        return Refusal(("TRACK_NOT_IN_POLICY",))
    if not decision.qualified_signal_ids:
        return Refusal(("NO_QUALIFIED_SIGNAL",))
    by_id = {s.signal_id: s for s in signals}
    if any(sid not in by_id for sid in decision.qualified_signal_ids):
        return Refusal(("QUALIFIED_SIGNAL_MISSING",))
    scopes = {(s.strategy_id, s.version, s.track): s.evidence_ref for s in policy.strategies}
    admitted = {(a.strategy_id, a.version, a.track, a.evidence_ref) for a in admissions
                if a.status == "ADMITTED"}
    strategies = []
    for sid in sorted(decision.qualified_signal_ids):
        signal = by_id[sid]
        if signal.source_kind != "NATIVE_STRATEGY":
            return Refusal(("STRATEGY_NOT_ADMITTED",))
        if (signal.canonical_id, signal.track, signal.direction) != \
                (decision.canonical_id, decision.track, "LONG"):
            return Refusal(("SIGNAL_DECISION_MISMATCH",))
        key = (signal.source_id, signal.source_version, signal.track)
        if key not in scopes:
            return Refusal(("STRATEGY_NOT_IN_POLICY",))
        if (*key, scopes[key]) not in admitted:
            return Refusal(("STRATEGY_NOT_ADMITTED",))
        strategies.append(f"{signal.source_id}@{signal.source_version}")
    instrument = policy.instrument(decision.canonical_id)
    if instrument is None:
        return Refusal(("INSTRUMENT_NOT_IN_POLICY",))
    if instrument.etoro_instrument_id in policy.protected_instrument_ids:
        return Refusal(("PROTECTED_INSTRUMENT",))
    if quote.canonical_id != decision.canonical_id:
        return Refusal(("QUOTE_INSTRUMENT_MISMATCH",))
    if not (quote.ask.is_finite() and quote.ask > 0):
        return Refusal(("QUOTE_INVALID",))
    if not _fresh(quote.quote_time, now, policy.max_quote_age_seconds):
        return Refusal(("QUOTE_STALE",))
    market = _session_open(now)
    if market is None:
        return Refusal(("MARKET_CALENDAR_UNCOVERED",))
    if not market:
        return Refusal(("MARKET_CLOSED",))
    day = now.astimezone(NEW_YORK).date()
    gate = evaluate_track_risk(
        TrackRiskState(budget.track, equity.equity, equity.peak_equity,
                       equity.session_start_equity, ledger.orders_on(budget.track, day)),
        TrackLimits(budget.track, budget.max_drawdown_pct, budget.max_daily_loss_pct,
                    budget.max_orders_per_day))
    if not gate.entries_allowed:
        return Refusal(gate.reasons)
    reference = _entry_reference(policy.digest(), decision)
    if ledger.has_entry(reference):
        return Refusal(("DUPLICATE_ENTRY",))
    if ledger.pending_entries(budget.track):
        return Refusal(("PENDING_ENTRY_UNRESOLVED",))
    if ledger.entries_on(budget.track, day) >= budget.max_new_entries_per_day:
        return Refusal(("DAILY_ENTRY_LIMIT",))
    if sum(1 for p in open_positions if p.track == budget.track) >= budget.max_open_positions:
        return Refusal(("MAX_OPEN_POSITIONS",))
    limit = (quote.ask * (1 + policy.max_limit_premium_pct)).quantize(
        Decimal("0.01"), rounding=ROUND_DOWN)
    stop = decision.sizing.stop_price
    if not (stop.is_finite() and Decimal(0) < stop < limit):
        return Refusal(("STOP_NOT_BELOW_LIMIT",))
    cap_units = (budget.max_position_notional / limit).quantize(
        Decimal("0.0001"), rounding=ROUND_DOWN)
    units = min(decision.sizing.quantity, cap_units)
    if units <= 0:
        return Refusal(("INSUFFICIENT_CAPACITY",))
    proposal = EntryProposal(
        reference_id=reference, policy_digest=policy.digest(), track=budget.track,
        canonical_id=decision.canonical_id,
        etoro_instrument_id=instrument.etoro_instrument_id, units=units, limit_price=limit,
        stop_price=stop, horizon_max_days=decision.sizing.horizon_max_days,
        strategies=tuple(strategies), decided_at=decision.decided_at, proposed_at=now)
    ledger.record_proposal("ENTRY", reference, budget.track, day, now,
                           f"{instrument.etoro_instrument_id}:{units}@{limit}")
    return proposal


def _sessions_elapsed(opened_at: datetime, now: datetime) -> int:
    """Exchange sessions that have opened after the position's opening session day."""
    day = opened_at.astimezone(NEW_YORK).date() + timedelta(days=1)
    last = now.astimezone(NEW_YORK).date()
    count = 0
    while day <= last:
        session = session_for(day)
        if session is not None and session.open_utc <= now:
            count += 1
        day += timedelta(days=1)
    return count


def plan_exits(
    policy: AutonomousDemoPolicy, ledger: PolicyLedger, positions: Sequence[ManagedPosition],
    quotes: Mapping[str, ExitQuote], now: datetime,
) -> ExitPlan:
    """Stop, horizon and pre-expiry exits for lineage-verified policy positions (full close)."""
    if now.tzinfo is None:
        raise PolicyRefused("timezone-aware time required")
    if ledger.policy_digest != policy.digest():
        raise PolicyRefused("ledger belongs to a different policy")
    if ledger.kill_switch_engaged():
        return ExitPlan((), ("KILL_SWITCH_ENGAGED",))
    exits: list[ExitProposal] = []
    alerts: list[str] = []
    market = _session_open(now)
    day = now.astimezone(NEW_YORK).date()
    for p in positions:
        ref = p.entry_reference
        if not p.lineage_verified:
            alerts.append(f"UNATTRIBUTED_POSITION:{ref}")
            continue
        if p.etoro_instrument_id in policy.protected_instrument_ids:
            alerts.append(f"PROTECTED_POSITION_NEVER_MANAGED:{ref}")
            continue
        if policy.budget(p.track) is None or policy.instrument(p.canonical_id) is None:
            alerts.append(f"POSITION_OUTSIDE_POLICY:{ref}")
            continue
        if not policy.active(now):
            alerts.append(f"POLICY_INACTIVE_POSITION_OPEN:{ref}")
            continue
        if ledger.pending_exit_for(ref):
            alerts.append(f"EXIT_PENDING:{ref}")
            continue
        quote = quotes.get(p.canonical_id)
        if quote is None or quote.canonical_id != p.canonical_id or not (
                quote.bid.is_finite() and quote.bid > 0
                and _fresh(quote.quote_time, now, policy.max_quote_age_seconds)):
            alerts.append(f"QUOTE_UNAVAILABLE:{ref}")
            continue
        if market is None:
            alerts.append(f"CALENDAR_UNCOVERED:{ref}")
            continue
        if not market:
            continue                                    # wait for the session; not an error
        try:
            elapsed = _sessions_elapsed(p.opened_at, now)
        except SchedulerError:
            alerts.append(f"CALENDAR_UNCOVERED:{ref}")
            continue
        if quote.bid <= p.stop_price:
            reason = "STOP_BREACHED"
        elif elapsed >= p.horizon_max_days:
            reason = "HORIZON_REACHED"
        elif policy.expires_at - now <= EXPIRY_FLATTEN_WINDOW:
            reason = "POLICY_EXPIRY_FLATTEN"
        else:
            continue
        attempt = ledger.exits_proposed_for(ref)
        exit_ref = hashlib.sha256(
            f"{policy.digest()}|{ref}|EXIT|{attempt}".encode("utf-8")).hexdigest()[:32]
        proposal = ExitProposal(exit_ref, ref, policy.digest(), p.track, p.canonical_id,
                                p.etoro_instrument_id, p.units, reason, now)
        ledger.record_proposal("EXIT", exit_ref, p.track, day, now, ref)
        exits.append(proposal)
    for code in alerts:
        ledger.alert(code, now)
    return ExitPlan(tuple(exits), tuple(alerts))
