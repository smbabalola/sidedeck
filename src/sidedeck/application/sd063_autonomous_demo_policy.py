"""SD-063 bounded autonomous eToro Demo policy (offline design; proposals only).

A policy is a canonical JSON document the **owner** reviews and releases by signing an SD-064
``autonomous_policy`` grant whose ``subject_digest`` is this policy's digest. This module never
signs, never unlocks the order transport and never sends anything. It turns current research
signals into bounded, single-use entry proposals and plans exits for positions recorded in its
own ledger. Every proposal is marked ``OFFLINE_PROPOSAL_NOT_SUBMITTED``. Implementing or
reviewing a policy releases nothing: the USD 1000 / 7-day figures are design ceilings.

Rules (all fail closed):

* **Release:** every call re-verifies the signed SD-064 grant through ``UnlockAuthority``
  (owner signature, revocation, window) and binds it to this policy (equal windows, matching
  digest). Time comes from the runtime's clock, never from the caller. A transport (SD-074) must
  still call ``UnlockAuthority.authorize_request(write=True, reference_id=proposal.reference_id)``
  before sending, which enforces the signed request/write caps and single-use references.
* **Scope:** eToro Demo only (Real permanently excluded), owner principal, window <= 7 days that
  contains a full XNYS session, SWING/POSITION only (DAY stays BLOCKED_EXTERNAL), total virtual
  capital <= USD 1000, explicit instrument mappings, non-empty protected baseline set that can
  never be in scope.
* **Decision:** SD-063 runs the SD-071 decision engine itself; callers cannot hand it a
  decision. A strategy counts only if it is named in the policy **and** its evidence file under
  ``evidence_root`` hashes to the SHA-256 the owner signed **and** an ADMITTED admission cites it.
  Agent signals never qualify.
* **Exposure (from the ledger, not the caller):** open positions, filled units and prices,
  pending and unresolved reservations, cash and realized P&L. Entries need cash and keep
  open + pending notional within the track capital; one position per instrument per policy.
* **Risk:** equity is derived from the ledger plus caller marks; SD-072 drawdown, daily-loss and
  order-frequency gates; an absolute cumulative-loss limit against virtual capital; stop width,
  horizon and ask-deviation bounds; limit IOC at most ``ask x (1 + premium)``, 1x, long-only.
* **Exits:** stop (checked first), horizon in exchange sessions, and a flatten from one hour
  before the last session close inside the window. Entries stop at that last session's open.
  The kill-switch blocks entries only; reduce-only exits continue. After expiry, open positions
  raise an alert for the owner's manual close (the grant can no longer authorize a send).
* **Recovery and concurrency:** every operation runs in one ``BEGIN IMMEDIATE`` transaction;
  one unresolved entry per track; each signal set is single-use; ``UNRESOLVED`` trips a
  persistent kill-switch and keeps the reservation counted.
* **Audit:** append-only, hash-chained SQLite ledger (UPDATE/DELETE refused by triggers) bound to
  one policy digest and mirrored by a separate anchor file (count + head). A dropped trigger,
  edited/deleted row, deleted ledger or stale anchor fails closed.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_DOWN, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sidedeck.application.sd064_unlock_grant import GrantRefused, UnlockAuthority, UnlockGrant
from sidedeck.application.sd068_track_scheduler import NEW_YORK, SchedulerError, session_for
from sidedeck.application.sd070_research_signal import TRACK_HORIZONS, ResearchSignal
from sidedeck.application.sd071_decision_engine import (
    Holding, MarketContext, PortfolioState, StrategyAdmission, TrackPolicy, decide,
)
from sidedeck.application.sd072_track_risk_limits import (
    TrackLimits, TrackRiskState, evaluate_track_risk,
)

SCHEMA = "sidedeck-autonomous-demo-policy/2"
BROKER = "etoro-demo"
OWNER_PRINCIPAL = "owner@sidedeck"
AUTONOMOUS_TRACKS = ("SWING", "POSITION")
MAX_POLICY_WINDOW = timedelta(days=7)
MAX_TOTAL_CAPITAL = Decimal("1000")
MAX_LIMIT_PREMIUM = Decimal("0.005")
MAX_QUOTE_AGE_SECONDS = 60
MAX_SIGNAL_AGE_SECONDS = 7 * 86400
MAX_ORDERS_PER_DAY = 20
MAX_RISK_PER_TRADE = Decimal("0.05")
MAX_STOP_ATR_MULTIPLE = Decimal("10")
MAX_STOP_DISTANCE = Decimal("0.25")      # stop at most 25 % below the limit
MAX_ASK_DEVIATION = Decimal("0.02")      # ask within 2 % of the decision's last price
MIN_ORDER_NOTIONAL = Decimal("10")
MAX_ENTRY_FILL_DELAY = timedelta(minutes=15)   # an IOC fills immediately or not at all
MAX_EXIT_FILL_DEVIATION = Decimal("0.10")      # exit fill within 10 % of the planned bid
FLATTEN_LEAD = timedelta(minutes=60)
MAX_EVIDENCE_BYTES = 50_000_000
SUBMISSION = "OFFLINE_PROPOSAL_NOT_SUBMITTED"
OUTCOMES = ("FILLED", "PARTIALLY_FILLED", "NOT_FILLED", "UNRESOLVED")
GENESIS = "0" * 64
_HEX64 = re.compile(r"[0-9a-f]{64}")
_REF = re.compile(r"[0-9a-f]{32}")
_FIELDS = {"schema", "policy_id", "broker", "issued_by", "not_before", "expires_at", "tracks",
           "strategies", "instruments", "protected_instrument_ids", "max_limit_premium_pct",
           "max_quote_age_seconds", "max_signal_age_seconds", "max_signal_data_age_seconds",
           "purpose"}
_TRACK_FIELDS = {"track", "virtual_capital", "max_position_notional", "max_open_positions",
                 "max_new_entries_per_day", "max_orders_per_day", "max_daily_loss_pct",
                 "max_drawdown_pct", "max_loss_pct", "risk_per_trade_pct", "stop_atr_multiple",
                 "max_correlation"}
_LEDGER_TABLES = {"meta", "events", "sqlite_sequence"}
_LEDGER_TRIGGERS = {"events_no_update", "events_no_delete", "meta_no_update", "meta_no_delete"}
ZERO = Decimal(0)


class PolicyRefused(PermissionError):
    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _is_int(value: Any) -> bool:
    return type(value) is int


def _decimal(value: Any, name: str) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise PolicyRefused(f"{name} must be a finite Decimal")
    return value


def _in_open_unit(value: Any, name: str, upper: Decimal = Decimal(1), *,
                  inclusive: bool = False) -> None:
    v = _decimal(value, name)
    if not (ZERO < v <= upper if inclusive else ZERO < v < upper):
        raise PolicyRefused(f"{name} out of range")


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
    max_loss_pct: Decimal                 # cumulative loss vs virtual capital
    risk_per_trade_pct: Decimal
    stop_atr_multiple: Decimal
    max_correlation: Decimal


@dataclass(frozen=True)
class StrategyScope:
    strategy_id: str
    version: str
    track: str
    evidence_ref: str                     # path relative to the runtime's evidence_root
    evidence_sha256: str                  # owner-signed digest of that evidence file


@dataclass(frozen=True)
class InstrumentScope:
    canonical_id: str
    etoro_instrument_id: int


def flatten_schedule(not_before: datetime, expires_at: datetime) -> tuple[datetime, datetime]:
    """(entry_cutoff, flatten_at) from the last XNYS session fully inside the window."""
    day = expires_at.astimezone(NEW_YORK).date()
    first = not_before.astimezone(NEW_YORK).date()
    while day >= first:
        session = session_for(day)
        if session is not None and not_before <= session.open_utc \
                and session.close_utc <= expires_at:
            return session.open_utc, session.close_utc - FLATTEN_LEAD
        day -= timedelta(days=1)
    raise PolicyRefused("policy window must contain a full exchange session for the flatten")


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
    max_signal_age_seconds: int
    max_signal_data_age_seconds: int
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
        _in_open_unit(self.max_limit_premium_pct, "limit premium", MAX_LIMIT_PREMIUM,
                      inclusive=True)
        if not _is_int(self.max_quote_age_seconds) or \
                not 0 < self.max_quote_age_seconds <= MAX_QUOTE_AGE_SECONDS:
            raise PolicyRefused("max quote age must be 1-60 seconds")
        for name in ("max_signal_age_seconds", "max_signal_data_age_seconds"):
            value = getattr(self, name)
            if not _is_int(value) or not 0 < value <= MAX_SIGNAL_AGE_SECONDS:
                raise PolicyRefused(f"{name} must be 1-{MAX_SIGNAL_AGE_SECONDS} seconds")
        if not isinstance(self.purpose, str) or not 0 < len(self.purpose) <= 500:
            raise PolicyRefused("purpose must be 1-500 characters")
        try:
            flatten_schedule(self.not_before, self.expires_at)
        except SchedulerError:
            raise PolicyRefused("exchange calendar does not cover the policy window") from None

    def _check_tracks(self) -> None:
        if not self.tracks:
            raise PolicyRefused("a policy needs at least one track")
        names = [b.track for b in self.tracks]
        if len(set(names)) != len(names):
            raise PolicyRefused("duplicate track budget")
        total = ZERO
        for b in self.tracks:
            if b.track == "DAY":
                raise PolicyRefused("DAY track is BLOCKED_EXTERNAL without approved intraday data")
            if b.track not in AUTONOMOUS_TRACKS:
                raise PolicyRefused(f"unknown track {b.track}")
            capital = _decimal(b.virtual_capital, "virtual_capital")
            notional = _decimal(b.max_position_notional, "max_position_notional")
            if capital <= 0:
                raise PolicyRefused("virtual capital must be positive")
            if not ZERO < notional <= capital:
                raise PolicyRefused("max position notional must be within the track capital")
            if notional < MIN_ORDER_NOTIONAL:
                raise PolicyRefused("max position notional is below the minimum order notional")
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
            for name in ("max_daily_loss_pct", "max_drawdown_pct", "max_loss_pct"):
                try:
                    _in_open_unit(getattr(b, name), name)
                except PolicyRefused:
                    raise PolicyRefused("loss limits must be in (0, 1)") from None
            _in_open_unit(b.risk_per_trade_pct, "risk per trade", MAX_RISK_PER_TRADE,
                          inclusive=True)
            _in_open_unit(b.stop_atr_multiple, "stop ATR multiple", MAX_STOP_ATR_MULTIPLE,
                          inclusive=True)
            _in_open_unit(b.max_correlation, "max correlation", inclusive=True)
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
            if not isinstance(s.evidence_sha256, str) or not _HEX64.fullmatch(s.evidence_sha256):
                raise PolicyRefused("strategy evidence needs a lower-case SHA-256 digest")
            if s.track not in tracks:
                raise PolicyRefused("strategy track is not a policy track")

    def _check_instruments(self) -> None:
        if not self.instruments:
            raise PolicyRefused("a policy needs at least one instrument")
        if not isinstance(self.protected_instrument_ids, frozenset) or not all(
                _is_int(i) and i > 0 for i in self.protected_instrument_ids):
            raise PolicyRefused("protected instrument ids must be a frozenset of integers")
        if not self.protected_instrument_ids:
            raise PolicyRefused("the protected baseline set must not be empty")
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

    def schedule(self) -> tuple[datetime, datetime]:
        return flatten_schedule(self.not_before, self.expires_at)

    def to_document(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA, "policy_id": self.policy_id, "broker": self.broker,
            "issued_by": self.issued_by,
            "not_before": self.not_before.astimezone(timezone.utc).isoformat(),
            "expires_at": self.expires_at.astimezone(timezone.utc).isoformat(),
            "tracks": [{name: (str(getattr(b, name)) if isinstance(getattr(b, name), Decimal)
                               else getattr(b, name)) for name in sorted(_TRACK_FIELDS)}
                       for b in sorted(self.tracks, key=lambda b: b.track)],
            "strategies": [[s.strategy_id, s.version, s.track, s.evidence_ref, s.evidence_sha256]
                           for s in sorted(self.strategies,
                                           key=lambda s: (s.strategy_id, s.version, s.track))],
            "instruments": [[i.canonical_id, i.etoro_instrument_id]
                            for i in sorted(self.instruments, key=lambda i: i.canonical_id)],
            "protected_instrument_ids": sorted(self.protected_instrument_ids),
            "max_limit_premium_pct": str(self.max_limit_premium_pct),
            "max_quote_age_seconds": self.max_quote_age_seconds,
            "max_signal_age_seconds": self.max_signal_age_seconds,
            "max_signal_data_age_seconds": self.max_signal_data_age_seconds,
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
        decimals = {"virtual_capital", "max_position_notional", "max_daily_loss_pct",
                    "max_drawdown_pct", "max_loss_pct", "risk_per_trade_pct",
                    "stop_atr_multiple", "max_correlation"}
        try:
            tracks = []
            for t in document["tracks"]:
                if not isinstance(t, dict) or set(t) != _TRACK_FIELDS:
                    raise PolicyRefused("track budget must contain exactly the schema fields")
                values: dict[str, Any] = {k: Decimal(v) if k in decimals else v
                                          for k, v in t.items()}
                tracks.append(TrackBudget(**values))
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
                max_signal_age_seconds=document["max_signal_age_seconds"],
                max_signal_data_age_seconds=document["max_signal_data_age_seconds"],
                purpose=document["purpose"], broker=document["broker"],
                issued_by=document["issued_by"])
        except (TypeError, ValueError, InvalidOperation) as exc:
            if isinstance(exc, PolicyRefused):
                raise
            raise PolicyRefused(f"malformed policy: {type(exc).__name__}") from None


def protective_subject(policy: AutonomousDemoPolicy) -> str:
    """SD-064 subject digest of a separate owner-signed protective-exit grant for a policy.

    Such a grant authorizes only reduce-only exits of positions recorded under this policy
    (e.g. after expiry or revocation of the policy grant); it never authorizes entries."""
    return hashlib.sha256(f"{policy.digest()}|protective-exit".encode("utf-8")).hexdigest()


def check_grant_binding(policy: AutonomousDemoPolicy, grant: UnlockGrant, now: datetime) -> None:
    """Bind an already-verified SD-064 grant to exactly this policy."""
    if grant.broker != BROKER:
        raise PolicyRefused("only eToro Demo grants can release a policy")
    if grant.kind != "autonomous_policy":
        raise PolicyRefused("grant kind must be autonomous_policy")
    if grant.issued_by != OWNER_PRINCIPAL:
        raise PolicyRefused("grant must be issued by the owner principal")
    if grant.subject_digest != policy.digest():
        raise PolicyRefused("grant subject digest does not match this policy")
    # Equal windows: a shorter grant would end before the flatten and strand positions.
    if (grant.not_before, grant.expires_at) != (policy.not_before, policy.expires_at):
        raise PolicyRefused("grant window must equal the policy window")
    if not (policy.active(now) and grant.not_before <= now < grant.expires_at):
        raise PolicyRefused("grant and policy must both be active now")


# ---- ledger --------------------------------------------------------------------------------

@dataclass(frozen=True)
class OpenPosition:
    entry_reference: str
    track: str
    canonical_id: str
    etoro_instrument_id: int
    sector: str
    units: Decimal
    avg_price: Decimal
    stop_price: Decimal
    horizon_max_days: int
    opened_at: datetime


@dataclass
class _Entry:
    reference: str
    track: str
    canonical_id: str
    instrument: int
    sector: str
    units: Decimal
    limit: Decimal
    stop: Decimal
    horizon: int
    proposed_at: datetime
    outcome: str | None = None
    filled: Decimal = ZERO
    avg_price: Decimal = ZERO
    filled_at: datetime | None = None
    exited: Decimal = ZERO
    realized: Decimal = ZERO


@dataclass
class _Exit:
    reference: str
    entry: str
    units: Decimal
    bid: Decimal
    proposed_at: datetime
    outcome: str | None = None


@dataclass
class _State:
    entries: dict[str, _Entry]
    exits: dict[str, _Exit]
    marks: dict[str, list[tuple[str, Decimal]]]   # track -> [(session_date, equity)]
    killed: bool
    quarantined: set[str]


_UNKNOWN_OUTCOMES = ("UNRESOLVED", "QUARANTINED")   # may exist at the broker; stay reserved


class PolicyLedger:
    """Append-only, hash-chained audit ledger for one policy digest, plus an anchor file."""

    def __init__(self, conn: sqlite3.Connection, policy_digest: str, anchor: Path) -> None:
        self._conn = conn
        self._anchor = anchor
        self._staged_anchor: tuple[int, str] | None = None
        self._staged: list[tuple[Any, ...]] = []
        self._in_txn = False
        self.policy_digest = policy_digest

    @classmethod
    def open(cls, path: Path, policy_digest: str, *, anchor_path: Path) -> "PolicyLedger":
        if not isinstance(policy_digest, str) or not _HEX64.fullmatch(policy_digest):
            raise PolicyRefused("policy digest must be one 64-hex digest")
        path, anchor = Path(path), Path(anchor_path)
        if anchor.resolve() == path.resolve():
            raise PolicyRefused("the policy ledger needs a separate anchor file")
        conn = sqlite3.connect(str(path), isolation_level=None, timeout=10)
        try:
            names = {n for (n,) in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'")}
            if names - _LEDGER_TABLES:
                raise PolicyRefused("refusing a SQLite file that is not an SD-063 policy ledger")
            ledger = cls(conn, policy_digest, anchor)
            if names:
                triggers = {n for (n,) in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'trigger'")}
                if not _LEDGER_TRIGGERS <= triggers:
                    raise PolicyRefused("ledger integrity triggers are missing")
                if conn.execute("SELECT policy_digest FROM meta").fetchall() != [(policy_digest,)]:
                    raise PolicyRefused("ledger belongs to a different policy")
                ledger._verify()
            else:
                if anchor.exists():
                    raise PolicyRefused("anchor exists without its ledger; refusing a fresh start")
                conn.executescript("""
                    BEGIN IMMEDIATE;
                    CREATE TABLE meta (policy_digest TEXT NOT NULL);
                    CREATE TABLE events (
                        seq INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL,
                        event TEXT NOT NULL, track TEXT, reference TEXT,
                        session_date TEXT, detail TEXT NOT NULL,
                        prev_hash TEXT NOT NULL, hash TEXT NOT NULL);
                    CREATE UNIQUE INDEX events_single_use
                        ON events(event, reference) WHERE reference IS NOT NULL;
                    CREATE TRIGGER events_no_update BEFORE UPDATE ON events
                        BEGIN SELECT RAISE(ABORT, 'append-only ledger'); END;
                    CREATE TRIGGER events_no_delete BEFORE DELETE ON events
                        BEGIN SELECT RAISE(ABORT, 'append-only ledger'); END;
                    CREATE TRIGGER meta_no_update BEFORE UPDATE ON meta
                        BEGIN SELECT RAISE(ABORT, 'policy binding is immutable'); END;
                    CREATE TRIGGER meta_no_delete BEFORE DELETE ON meta
                        BEGIN SELECT RAISE(ABORT, 'policy binding is immutable'); END;
                """)
                conn.execute("INSERT INTO meta VALUES (?)", (policy_digest,))
                ledger._write_anchor(0, GENESIS)
                conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            conn.close()
            raise
        return ledger

    def close(self) -> None:
        self._conn.close()

    # integrity
    @staticmethod
    def _hash(prev: str, row: Sequence[Any]) -> str:
        return hashlib.sha256(json.dumps([prev, *row], separators=(",", ":"))
                              .encode("utf-8")).hexdigest()

    def _head(self) -> tuple[int, str]:
        count, head = 0, GENESIS
        for row in self._conn.execute("SELECT at, event, track, reference, session_date, detail,"
                                      " prev_hash, hash FROM events ORDER BY seq"):
            if row[6] != head or self._hash(head, row[:6]) != row[7]:
                raise PolicyRefused("ledger hash chain is broken")
            count, head = count + 1, row[7]
        return count, head

    def _read_anchor(self) -> dict[str, Any]:
        try:
            anchor = json.loads(self._anchor.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise PolicyRefused("ledger anchor is missing or unreadable") from None
        if not isinstance(anchor, dict) or anchor.get("policy_digest") != self.policy_digest:
            raise PolicyRefused("ledger anchor belongs to a different policy")
        return anchor

    def _verify(self) -> tuple[int, str]:
        count, head = self._head()
        anchor = self._read_anchor()
        if (anchor.get("count"), anchor.get("head")) != (count, head):
            raise PolicyRefused("ledger does not match its anchor (edited, truncated or replaced)")
        return count, head

    def _write_anchor(self, count: int, head: str, prev: tuple[int, str] | None = None,
                      pending: Sequence[Sequence[Any]] = ()) -> None:
        """Anchor = committed head plus a write-ahead copy of the last transaction's rows."""
        prev_count, prev_head = prev or (count, head)
        tmp = self._anchor.with_name(self._anchor.name + ".tmp")
        payload = json.dumps({"policy_digest": self.policy_digest, "count": count,
                              "head": head, "prev_count": prev_count, "prev_head": prev_head,
                              "last_rows": [list(r) for r in pending]}).encode("utf-8")
        with open(tmp, "wb") as handle:                      # durable before the rename
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, self._anchor)

    @staticmethod
    def inspect_recovery(anchor_path: Path) -> dict[str, Any]:
        """Read-only: what ``recover_last_transaction`` would replay, for the owner to check
        (event, track, reference and detail of every row) before confirming its head."""
        try:
            anchor = json.loads(Path(anchor_path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise PolicyRefused("ledger anchor is missing or unreadable") from None
        rows = anchor.get("last_rows") or []
        return {"expected_head": anchor.get("head"), "count": anchor.get("count"),
                "rows": [{"at": r[0], "event": r[1], "track": r[2], "reference": r[3],
                          "detail": r[5]} for r in rows if isinstance(r, list) and len(r) == 8]}

    @classmethod
    def recover_last_transaction(cls, path: Path, policy_digest: str, *, anchor_path: Path,
                                 expected_head: str, at: datetime) -> "PolicyLedger":
        """Owner-run recovery when the ledger is behind its anchor by the last transaction.

        That happens after a crash between the anchor write and COMMIT, or if someone deleted
        the last committed transaction. The anchor holds a write-ahead copy of those rows.
        Recovery requires the owner to confirm ``expected_head`` from ``inspect_recovery``,
        and checks the rows chain from the ledger head to that head. The rows are then stored
        as quarantined data only (never as state), the proposals they name become QUARANTINED,
        and the kill-switch is tripped."""
        conn = sqlite3.connect(str(path), isolation_level=None, timeout=10)
        ledger = cls(conn, policy_digest, Path(anchor_path))
        try:
            conn.execute("BEGIN IMMEDIATE")                  # take the write lock first
            ledger._in_txn = True
            triggers = {n for (n,) in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'trigger'")}
            if not _LEDGER_TRIGGERS <= triggers:
                raise PolicyRefused("ledger integrity triggers are missing")
            if conn.execute("SELECT policy_digest FROM meta").fetchall() != [(policy_digest,)]:
                raise PolicyRefused("ledger belongs to a different policy")
            count, head = ledger._head()
            anchor = ledger._read_anchor()
            rows = anchor.get("last_rows") or []
            if (anchor.get("prev_count"), anchor.get("prev_head")) != (count, head) or not rows \
                    or anchor.get("count") != count + len(rows):
                raise PolicyRefused("ledger is not exactly the last anchored transaction behind")
            cursor = head
            for r in rows:
                if not isinstance(r, list) or len(r) != 8 or r[6] != cursor \
                        or cls._hash(cursor, r[:6]) != r[7]:
                    raise PolicyRefused("anchored write-ahead rows do not chain from the ledger")
                cursor = r[7]
            if cursor != anchor.get("head"):
                raise PolicyRefused("anchored write-ahead rows do not reach the anchor head")
            if expected_head != cursor:
                raise PolicyRefused("owner-confirmed head does not match the anchored rows")
            # The anchored rows are never trusted as state (the chain is unkeyed, so an
            # anchor-only edit could forge them). They are kept verbatim as quarantined data;
            # our own proposals they name become QUARANTINED (still reserved, alerted, owner
            # must check the broker and close manually).
            references = sorted({r[3] for r in rows
                                 if isinstance(r[3], str) and _REF.fullmatch(r[3])})
            ledger._staged, ledger._staged_anchor = [], (count, head)
            ledger._append(at, "RECOVERY_QUARANTINE", detail={
                "anchored_head": cursor, "references": references,
                "rows": [list(r[:6]) for r in rows]})
            ledger._append(at, "KILL_SWITCH", detail={"reason": "LAST_TRANSACTION_QUARANTINED"})
            assert ledger._staged_anchor is not None
            ledger._write_anchor(*ledger._staged_anchor, prev=(count, head),
                                 pending=ledger._staged)
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            conn.close()
            raise
        finally:
            ledger._in_txn, ledger._staged_anchor, ledger._staged = False, None, []
        return ledger

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Serialise all checks and writes (``BEGIN IMMEDIATE``) and re-verify integrity."""
        if self._in_txn:
            raise PolicyRefused("nested ledger transaction")
        self._conn.execute("BEGIN IMMEDIATE")
        self._in_txn = True
        try:
            before = self._verify()
            yield
            if self._staged_anchor is not None:
                self._write_anchor(*self._staged_anchor, prev=before, pending=self._staged)
            self._conn.execute("COMMIT")
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        finally:
            self._in_txn, self._staged_anchor, self._staged = False, None, []

    def _append(self, at: datetime, event: str, *, track: str | None = None,
                reference: str | None = None, session_date: date | None = None,
                detail: Mapping[str, Any] | None = None) -> None:
        if not self._in_txn:
            raise PolicyRefused("ledger writes require a transaction")
        count, head = self._staged_anchor or self._head()
        row = (at.astimezone(timezone.utc).isoformat(), event, track, reference,
               session_date.isoformat() if session_date else None,
               json.dumps(dict(detail or {}), sort_keys=True, separators=(",", ":")))
        digest = self._hash(head, row)
        self._conn.execute("INSERT INTO events (at, event, track, reference, session_date, "
                           "detail, prev_hash, hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                           (*row, head, digest))
        self._staged.append((*row, head, digest))
        self._staged_anchor = (count + 1, digest)

    # derived state
    def state(self) -> _State:
        entries: dict[str, _Entry] = {}
        exits: dict[str, _Exit] = {}
        marks: dict[str, list[tuple[str, Decimal]]] = {}
        killed = False
        quarantined: set[str] = set()
        for event, track, ref, day, at, raw in self._conn.execute(
                "SELECT event, track, reference, session_date, at, detail FROM events "
                "ORDER BY seq"):
            d = json.loads(raw)
            if event == "KILL_SWITCH":
                killed = True
            elif event == "EQUITY_MARK":
                marks.setdefault(track, []).append((day, Decimal(d["equity"])))
            elif event == "ENTRY_PROPOSED":
                entries[ref] = _Entry(ref, track, d["canonical_id"], d["instrument"], d["sector"],
                                      Decimal(d["units"]), Decimal(d["limit"]),
                                      Decimal(d["stop"]), d["horizon"],
                                      datetime.fromisoformat(at))
            elif event in ("ENTRY_RESOLVED", "ENTRY_RECONCILED"):
                e = entries[ref]
                e.outcome, e.filled = d["outcome"], Decimal(d["units"])
                e.avg_price = Decimal(d["price"])
                e.filled_at = datetime.fromisoformat(at)
            elif event == "EXIT_PROPOSED":
                exits[ref] = _Exit(ref, d["entry"], Decimal(d["units"]), Decimal(d["bid"]),
                                   datetime.fromisoformat(at))
            elif event in ("EXIT_RESOLVED", "EXIT_RECONCILED"):
                x = exits[ref]
                x.outcome = d["outcome"]
                e = entries[x.entry]
                units, price = Decimal(d["units"]), Decimal(d["price"])
                e.exited += units
                e.realized += units * (price - e.avg_price)
            elif event == "RECOVERY_QUARANTINE":
                for qref in d["references"]:
                    quarantined.add(qref)
                    target = entries.get(qref) or exits.get(qref)
                    if target is not None and target.outcome is None:
                        target.outcome = "QUARANTINED"
        return _State(entries, exits, marks, killed, quarantined)

    def count_events(self, events: tuple[str, ...], track: str, day: date) -> int:
        marks = ", ".join("?" for _ in events)
        return int(self._conn.execute(
            f"SELECT COUNT(*) FROM events WHERE event IN ({marks}) AND track = ? "
            "AND session_date = ?", (*events, track, day.isoformat())).fetchone()[0])

    def kill_switch_engaged(self) -> bool:
        return self.state().killed

    def open_positions(self) -> tuple[OpenPosition, ...]:
        return _open_positions(self.state())

    def trip_kill_switch(self, reason: str, at: datetime) -> None:
        with self.transaction():
            self._append(at, "KILL_SWITCH", detail={"reason": reason[:200]})

    def _target(self, st: _State, evidence: "FillEvidence") -> _Entry | _Exit:
        if not isinstance(evidence, FillEvidence):
            raise PolicyRefused("only verified broker-reconciliation evidence can resolve")
        target = st.entries.get(evidence.reference) or st.exits.get(evidence.reference)
        if target is None:
            raise PolicyRefused("unknown proposal reference")
        return target

    def _record(self, kind: str, event: str, evidence: "FillEvidence", units: Decimal,
                price: Decimal) -> None:
        filled = evidence.outcome in ("FILLED", "PARTIALLY_FILLED")
        self._append(evidence.at, f"{kind}_{event}", reference=evidence.reference, detail={
            "outcome": evidence.outcome, "units": str(units if filled else ZERO),
            "price": str(price if filled else ZERO), "source": evidence.source_id,
            "broker_order_id": evidence.broker_order_id, "lookup_sha256": evidence.lookup_sha256,
            "envelope_mac": evidence.envelope_mac, "envelope_nonce": evidence.envelope_nonce})

    def resolve(self, evidence: "FillEvidence") -> None:
        """Record the reconciled broker outcome from verified evidence (SD-074). UNRESOLVED
        trips the persistent kill-switch and keeps the reservation counted."""
        with self.transaction():
            target = self._target(self.state(), evidence)
            units, price = _check_resolution(target, evidence.outcome, evidence.units,
                                             evidence.price, evidence.at)
            kind = "ENTRY" if isinstance(target, _Entry) else "EXIT"
            self._record(kind, "RESOLVED", evidence, units, price)
            if evidence.outcome == "UNRESOLVED":
                self._append(evidence.at, "KILL_SWITCH",
                             detail={"reason": f"UNRESOLVED_{kind}:{evidence.reference}"})

    def reconcile_unknown(self, evidence: "FillEvidence") -> None:
        """Settle an UNRESOLVED or QUARANTINED proposal with independent broker evidence.

        Operator approval is not an input: only verified reconciliation evidence (with the
        broker order lookup digest) can turn it into a position or release its reservation.
        The kill-switch stays engaged."""
        with self.transaction():
            target = self._target(self.state(), evidence)
            if target.outcome not in _UNKNOWN_OUTCOMES:
                raise PolicyRefused("only UNRESOLVED or QUARANTINED proposals are reconciled")
            if evidence.outcome == "UNRESOLVED":
                raise PolicyRefused("reconciliation needs a final broker outcome")
            units, price = _check_resolution(replace(target, outcome=None), evidence.outcome,
                                             evidence.units, evidence.price, evidence.at)
            kind = "ENTRY" if isinstance(target, _Entry) else "EXIT"
            self._record(kind, "RECONCILED", evidence, units, price)


_EVIDENCE_TOKEN = object()
_VERIFIED_INPUTS = object()      # passed only by sd074.AuthenticatedRuntime (in-process guard)


@dataclass(frozen=True)
class FillEvidence:
    """Broker-reconciliation evidence for one proposal reference.

    Built only by the SD-074 input verifier from an envelope sealed by the registered
    broker-reconciliation source (``_new_fill_evidence`` is the in-process constructor). The
    private token is a guard against accidental construction, not the security boundary."""
    reference: str
    outcome: str
    units: Decimal
    price: Decimal
    at: datetime
    source_id: str
    broker_order_id: str
    lookup_sha256: str
    envelope_mac: str = ""
    envelope_nonce: str = ""
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._token is not _EVIDENCE_TOKEN:
            raise PolicyRefused("fill evidence must come from the verified reconciliation path")
        if not isinstance(self.reference, str) or not _REF.fullmatch(self.reference):
            raise PolicyRefused("unknown proposal reference")
        if self.outcome not in OUTCOMES:
            raise PolicyRefused(f"invalid outcome; expected one of {OUTCOMES}")
        if not isinstance(self.lookup_sha256, str) or not _HEX64.fullmatch(self.lookup_sha256):
            raise PolicyRefused("fill evidence needs the broker lookup digest")
        if not (isinstance(self.broker_order_id, str) and self.broker_order_id.strip()
                and isinstance(self.source_id, str) and self.source_id.strip()):
            raise PolicyRefused("fill evidence needs a broker order id and source")
        if not isinstance(self.at, datetime) or self.at.tzinfo is None:
            raise PolicyRefused("fill evidence time must be timezone-aware")


def _new_fill_evidence(**fields: Any) -> FillEvidence:
    return FillEvidence(**fields, _token=_EVIDENCE_TOKEN)


def _check_resolution(target: _Entry | _Exit, outcome: str, filled_units: Any, avg_price: Any,
                      at: datetime) -> tuple[Decimal, Decimal]:
    """Shared plausibility rules for live resolutions and replayed (recovered) rows."""
    if outcome not in OUTCOMES:
        raise PolicyRefused(f"invalid outcome; expected one of {OUTCOMES}")
    if target.outcome is not None:
        raise PolicyRefused("proposal already resolved")
    if at.tzinfo is None or at < target.proposed_at:
        raise PolicyRefused("resolution time precedes the proposal")
    try:
        units, price = _decimal(filled_units, "filled units"), _decimal(avg_price, "average price")
    except PolicyRefused:
        raise PolicyRefused("fill outcome needs finite units and price") from None
    if outcome in ("FILLED", "PARTIALLY_FILLED"):
        if not (ZERO < units <= target.units and price > 0):
            raise PolicyRefused("fill outcome must have 0 < units <= proposed and price > 0")
        if outcome == "FILLED" and units != target.units:
            raise PolicyRefused("FILLED must fill the proposed units exactly")
        if isinstance(target, _Entry):
            if price > target.limit:
                raise PolicyRefused("entry fill price above the limit")
            if price <= target.stop:
                raise PolicyRefused("entry fill price at or below the stop is implausible")
            if at > target.proposed_at + MAX_ENTRY_FILL_DELAY:
                raise PolicyRefused("entry fill time is outside the IOC fill window")
        elif abs(price - target.bid) > target.bid * MAX_EXIT_FILL_DEVIATION:
            raise PolicyRefused("exit fill price deviates from the planned bid")
    elif units != 0:
        raise PolicyRefused("only fill outcomes carry units")
    return units, price


def _open_positions(st: _State) -> tuple[OpenPosition, ...]:
    out = []
    for e in st.entries.values():
        if e.outcome in ("FILLED", "PARTIALLY_FILLED") and e.filled - e.exited > 0:
            assert e.filled_at is not None
            out.append(OpenPosition(e.reference, e.track, e.canonical_id, e.instrument, e.sector,
                                    e.filled - e.exited, e.avg_price, e.stop, e.horizon,
                                    e.filled_at))
    return tuple(out)


# ---- runtime -------------------------------------------------------------------------------

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
    authority: str = "policy"              # "policy" or "protective" (SD-064 grant to use)


@dataclass(frozen=True)
class ExitPlan:
    exits: tuple[ExitProposal, ...]
    alerts: tuple[str, ...]


def _session_open(now: datetime) -> bool | None:
    try:
        session = session_for(now.astimezone(NEW_YORK).date())
    except SchedulerError:
        return None
    return session is not None and session.open_utc <= now < session.close_utc


def _fresh(quote_time: datetime, now: datetime, max_age_seconds: int) -> bool:
    return (quote_time.tzinfo is not None and quote_time <= now
            and now - quote_time <= timedelta(seconds=max_age_seconds))


def _sessions_elapsed(opened_at: datetime, now: datetime) -> int:
    day = opened_at.astimezone(NEW_YORK).date() + timedelta(days=1)
    last = now.astimezone(NEW_YORK).date()
    count = 0
    while day <= last:
        session = session_for(day)
        if session is not None and session.open_utc <= now:
            count += 1
        day += timedelta(days=1)
    return count


class AutonomousDemoRuntime:
    """Proposal engine for one released policy. Holds no broker transport or credentials."""

    def __init__(self, policy: AutonomousDemoPolicy, ledger: PolicyLedger, *,
                 authority: UnlockAuthority, grant_document: Mapping[str, Any],
                 grant_signature: str, evidence_root: Path,
                 clock: Callable[[], datetime] = _utc_now,
                 protective_grant: tuple[Mapping[str, Any], str] | None = None,
                 allow_unverified_inputs: bool = False) -> None:
        if ledger.policy_digest != policy.digest():
            raise PolicyRefused("ledger belongs to a different policy")
        self.policy, self.ledger = policy, ledger
        self._authority, self._clock = authority, clock
        self._grant_document, self._grant_signature = dict(grant_document), grant_signature
        self._allow_unverified = allow_unverified_inputs is True
        self._protective = None if protective_grant is None else \
            (dict(protective_grant[0]), protective_grant[1])
        self._evidence_root = Path(evidence_root).resolve()

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None:
            raise PolicyRefused("runtime clock must be timezone-aware")
        return now.astimezone(timezone.utc)

    def _grant_valid(self, now: datetime) -> bool:
        try:
            grant = self._authority.check(document=self._grant_document,
                                          signature=self._grant_signature,
                                          subject_digest=self.policy.digest(), now=now)
            check_grant_binding(self.policy, grant, now)
        except (GrantRefused, PolicyRefused):
            return False
        return True

    def _evidence_ok(self, scope: StrategyScope) -> bool:
        try:
            path = (self._evidence_root / scope.evidence_ref).resolve()
            if not path.is_relative_to(self._evidence_root) or not path.is_file() \
                    or path.stat().st_size > MAX_EVIDENCE_BYTES:
                return False
            return hashlib.sha256(path.read_bytes()).hexdigest() == scope.evidence_sha256
        except OSError:
            return False

    def _equity(self, st: _State, track: str, capital: Decimal,
                marks: Mapping[str, Decimal]) -> Decimal | None:
        equity = capital + sum((e.realized for e in st.entries.values() if e.track == track), ZERO)
        for p in _open_positions(st):
            if p.track != track:
                continue
            mark = marks.get(p.canonical_id)
            if mark is None or not mark.is_finite() or mark <= 0:
                return None
            equity += p.units * (mark - p.avg_price)
        return equity

    def propose_entry(
        self, *, track: str, signals: Sequence[ResearchSignal],
        admissions: Sequence[StrategyAdmission], market: MarketContext, quote: EntryQuote,
        marks: Mapping[str, Decimal], _verified: object = None,
    ) -> EntryProposal | Refusal:
        """Run the decision engine and every policy gate; return one unsent proposal.

        Production callers go through ``sd074.AuthenticatedRuntime``; direct calls with
        caller-built inputs are refused unless the runtime was built with
        ``allow_unverified_inputs=True`` (offline tests only)."""
        if not (self._allow_unverified or _verified is _VERIFIED_INPUTS):
            return Refusal(("UNVERIFIED_INPUTS_REFUSED",))
        try:
            with self.ledger.transaction():
                return self._propose_entry(track, signals, admissions, market, quote, marks)
        except (InvalidOperation, ArithmeticError):
            return Refusal(("INVALID_NUMERIC_INPUT",))
        except sqlite3.IntegrityError:
            return Refusal(("DUPLICATE_ENTRY",))

    def _propose_entry(
        self, track: str, signals: Sequence[ResearchSignal],
        admissions: Sequence[StrategyAdmission], market: MarketContext, quote: EntryQuote,
        marks: Mapping[str, Decimal],
    ) -> EntryProposal | Refusal:
        policy, ledger = self.policy, self.ledger
        now = self._now()
        st = ledger.state()
        if st.killed:
            return Refusal(("KILL_SWITCH_ENGAGED",))
        if not policy.active(now):
            return Refusal(("POLICY_NOT_ACTIVE",))
        entry_cutoff, _ = policy.schedule()
        if now >= entry_cutoff:
            return Refusal(("ENTRY_WINDOW_CLOSED",))
        if not self._grant_valid(now):
            return Refusal(("GRANT_NOT_VALID",))
        budget = policy.budget(track)
        if budget is None:
            return Refusal(("TRACK_NOT_IN_POLICY",))
        instrument = policy.instrument(market.canonical_id)
        if instrument is None:
            return Refusal(("INSTRUMENT_NOT_IN_POLICY",))
        if instrument.etoro_instrument_id in policy.protected_instrument_ids:
            return Refusal(("PROTECTED_INSTRUMENT",))
        market_open = _session_open(now)
        if market_open is None:
            return Refusal(("MARKET_CALENDAR_UNCOVERED",))
        if not market_open:
            return Refusal(("MARKET_CLOSED",))

        # Equity from the ledger + marks. The session's first mark is the daily-loss baseline;
        # further marks are written only on a new high, so polling cannot grow the ledger.
        day = now.astimezone(NEW_YORK).date()
        equity = self._equity(st, track, budget.virtual_capital, marks)
        if equity is None:
            return Refusal(("MARK_MISSING_FOR_OPEN_POSITION",))
        history = st.marks.get(track, [])
        prior_peak = max([budget.virtual_capital, *(v for _, v in history)])
        start = next((v for d, v in history if d == day.isoformat()), None)
        if start is None or equity > prior_peak:
            ledger._append(now, "EQUITY_MARK", track=track, session_date=day,
                           detail={"equity": str(equity)})
        start = equity if start is None else start
        peak = max(prior_peak, equity)
        if equity <= budget.virtual_capital * (1 - budget.max_loss_pct):
            return Refusal(("CUMULATIVE_LOSS_LIMIT",))

        # Strategy admission: policy scope + owner-signed evidence digest + ADMITTED record.
        verified = {(s.strategy_id, s.version) for s in policy.strategies
                    if s.track == track and self._evidence_ok(s)
                    and any((a.strategy_id, a.version, a.track, a.evidence_ref, a.status)
                            == (s.strategy_id, s.version, track, s.evidence_ref, "ADMITTED")
                            for a in admissions)}
        trusted_admissions = [a for a in admissions if a.track == track
                              and (a.strategy_id, a.version) in verified]

        open_positions = _open_positions(st)
        pending = [e for e in st.entries.values() if e.outcome is None]
        unresolved = [e for e in st.entries.values() if e.outcome in _UNKNOWN_OUTCOMES]
        reserved = {e.reference: e.units * e.limit for e in pending + unresolved}
        track_open_cost = sum((p.units * p.avg_price for p in open_positions if p.track == track),
                              ZERO)
        track_reserved = sum((v for r, v in reserved.items() if st.entries[r].track == track), ZERO)
        realized = sum((e.realized for e in st.entries.values() if e.track == track), ZERO)
        cash = budget.virtual_capital + realized - track_open_cost - track_reserved
        holdings = tuple(Holding(p.canonical_id, p.track, p.units * p.avg_price, p.sector)
                         for p in open_positions)
        decision = decide(
            [s for s in signals if s.track == track], trusted_admissions,
            TrackPolicy(
                policy_id=policy.policy_id, track=track, virtual_capital=budget.virtual_capital,
                max_position_pct=budget.max_position_notional / budget.virtual_capital,
                max_positions=budget.max_open_positions, max_gross_exposure_pct=Decimal(1),
                max_instrument_total_pct=budget.max_position_notional / budget.virtual_capital,
                max_sector_pct=Decimal(1), max_correlation=budget.max_correlation,
                risk_per_trade_pct=budget.risk_per_trade_pct,
                stop_atr_multiple=budget.stop_atr_multiple, min_notional=MIN_ORDER_NOTIONAL,
                max_signal_age=timedelta(seconds=policy.max_signal_age_seconds),
                max_signal_data_age=timedelta(seconds=policy.max_signal_data_age_seconds),
                max_price_age=timedelta(seconds=policy.max_quote_age_seconds),
                expires_at=entry_cutoff, allowed_strategies=frozenset(verified),
                allowed_instruments=frozenset(i.canonical_id for i in policy.instruments)),
            PortfolioState(holdings, {track: max(cash, ZERO)}), market, now)
        if decision.status != "ELIGIBLE" or decision.sizing is None:
            return Refusal((f"DECISION_{decision.status}", *decision.reasons))

        if quote.canonical_id != market.canonical_id:
            return Refusal(("QUOTE_INSTRUMENT_MISMATCH",))
        if not (quote.ask.is_finite() and quote.ask > 0):
            return Refusal(("QUOTE_INVALID",))
        if not _fresh(quote.quote_time, now, policy.max_quote_age_seconds):
            return Refusal(("QUOTE_STALE",))
        if abs(quote.ask - market.last_price) > market.last_price * MAX_ASK_DEVIATION:
            return Refusal(("ASK_DEVIATES_FROM_DECISION_PRICE",))

        orders_today = ledger.count_events(("ENTRY_PROPOSED", "EXIT_PROPOSED"), track, day)
        gate = evaluate_track_risk(TrackRiskState(track, equity, peak, start, orders_today),
                                   TrackLimits(track, budget.max_drawdown_pct,
                                               budget.max_daily_loss_pct,
                                               budget.max_orders_per_day))
        if not gate.entries_allowed:
            return Refusal(gate.reasons)

        qualified = sorted(decision.qualified_signal_ids)
        reference = hashlib.sha256("|".join((policy.digest(), track, market.canonical_id,
                                             *qualified)).encode("utf-8")).hexdigest()[:32]
        if reference in st.entries:
            return Refusal(("DUPLICATE_ENTRY",))
        if any(e.track == track for e in pending):
            return Refusal(("PENDING_ENTRY_UNRESOLVED",))
        entries_today = ledger.count_events(("ENTRY_PROPOSED",), track, day)
        if entries_today >= budget.max_new_entries_per_day:
            return Refusal(("DAILY_ENTRY_LIMIT",))
        if any(e.canonical_id == market.canonical_id for e in pending + unresolved) or any(
                p.canonical_id == market.canonical_id for p in open_positions):
            return Refusal(("INSTRUMENT_ALREADY_HELD_OR_PENDING",))
        open_count = sum(1 for p in open_positions if p.track == track) + sum(
            1 for e in unresolved if e.track == track)
        if open_count >= budget.max_open_positions:
            return Refusal(("MAX_OPEN_POSITIONS",))

        limit = (quote.ask * (1 + policy.max_limit_premium_pct)).quantize(
            Decimal("0.01"), rounding=ROUND_DOWN)
        stop = decision.sizing.stop_price
        if not (stop.is_finite() and ZERO < stop < limit):
            return Refusal(("STOP_NOT_BELOW_LIMIT",))
        if stop < limit * (1 - MAX_STOP_DISTANCE):
            return Refusal(("STOP_TOO_WIDE",))
        low, high = TRACK_HORIZONS[track]
        horizon = decision.sizing.horizon_max_days
        if not low <= horizon <= high:
            return Refusal(("HORIZON_OUT_OF_TRACK_BOUNDS",))
        units = min(decision.sizing.quantity, (budget.max_position_notional / limit).quantize(
            Decimal("0.0001"), rounding=ROUND_DOWN))
        notional = units * limit
        if units <= 0 or notional < MIN_ORDER_NOTIONAL:
            return Refusal(("INSUFFICIENT_CAPACITY",))
        if notional > cash or track_open_cost + track_reserved + notional > budget.virtual_capital:
            return Refusal(("EXPOSURE_OR_CASH_LIMIT",))

        signal_by_id = {s.signal_id: s for s in signals}
        strategies = tuple(sorted({f"{signal_by_id[q].source_id}@{signal_by_id[q].source_version}"
                                   for q in qualified}))
        ledger._append(now, "ENTRY_PROPOSED", track=track, reference=reference, session_date=day,
                       detail={"canonical_id": market.canonical_id,
                               "instrument": instrument.etoro_instrument_id,
                               "sector": market.sector, "units": str(units),
                               "limit": str(limit), "stop": str(stop), "horizon": horizon,
                               "strategies": list(strategies)})
        return EntryProposal(
            reference_id=reference, policy_digest=policy.digest(), track=track,
            canonical_id=market.canonical_id, etoro_instrument_id=instrument.etoro_instrument_id,
            units=units, limit_price=limit, stop_price=stop, horizon_max_days=horizon,
            strategies=strategies, proposed_at=now)

    def plan_exits(self, *, bids: Mapping[str, ExitQuote],
                   _verified: object = None) -> ExitPlan:
        """Reduce-only exits for ledger positions: stop, horizon, pre-expiry flatten."""
        if not (self._allow_unverified or _verified is _VERIFIED_INPUTS):
            return ExitPlan((), ("UNVERIFIED_INPUTS_REFUSED",))
        try:
            with self.ledger.transaction():
                return self._plan_exits(bids)
        except (InvalidOperation, ArithmeticError):
            return ExitPlan((), ("INVALID_NUMERIC_INPUT",))

    def _plan_exits(self, bids: Mapping[str, ExitQuote]) -> ExitPlan:
        policy, ledger = self.policy, self.ledger
        now = self._now()
        st = ledger.state()
        alerts: list[str] = ["KILL_SWITCH_ENGAGED"] if st.killed else []
        positions = _open_positions(st)
        alerts += [f"{e.outcome}_ENTRY:{e.reference}" for e in st.entries.values()
                   if e.outcome in _UNKNOWN_OUTCOMES]
        alerts += [f"QUARANTINED_UNKNOWN_REFERENCE:{q}" for q in sorted(st.quarantined)
                   if q not in st.entries and q not in st.exits]
        if not positions:
            return self._finish(now, (), alerts)
        authority = "policy"
        if not (policy.active(now) and self._grant_valid(now)):
            # Protective authority only after expiry: a revocation (anyone may revoke) or a
            # transient grant failure must not force a liquidation.
            if not policy.active(now) and self._protective_valid(now):
                # Separate owner-signed protective-exit authority: reduce-only, no entries.
                authority = "protective"
                alerts.append("PROTECTIVE_EXIT_AUTHORITY_IN_USE")
            elif not policy.active(now):
                return self._finish(now, (), alerts + [
                    f"POLICY_EXPIRED_POSITION_OPEN:{p.entry_reference}" for p in positions])
            else:
                return self._finish(now, (), alerts + [
                    f"GRANT_NOT_VALID_POSITION_OPEN:{p.entry_reference}" for p in positions])
        market_open = _session_open(now)
        _, flatten_at = policy.schedule()
        day = now.astimezone(NEW_YORK).date()
        exits: list[ExitProposal] = []
        for p in positions:
            ref = p.entry_reference
            if any(x.entry == ref and x.outcome is None for x in st.exits.values()):
                alerts.append(f"EXIT_PENDING:{ref}")
                continue
            if any(x.entry == ref and x.outcome in _UNKNOWN_OUTCOMES for x in st.exits.values()):
                alerts.append(f"EXIT_UNRESOLVED:{ref}")
                continue
            quote = bids.get(p.canonical_id)
            if quote is None or quote.canonical_id != p.canonical_id or not (
                    quote.bid.is_finite() and quote.bid > 0
                    and _fresh(quote.quote_time, now, policy.max_quote_age_seconds)):
                alerts.append(f"QUOTE_UNAVAILABLE:{ref}")
                continue
            if market_open is None:
                alerts.append(f"CALENDAR_UNCOVERED:{ref}")
                continue
            if not market_open:
                continue                                    # wait for the session
            if quote.bid <= p.stop_price:                   # stop first: needs no calendar math
                reason = "STOP_BREACHED"
            elif authority == "protective":
                reason = "PROTECTIVE_FLATTEN"
            elif now >= flatten_at:
                reason = "POLICY_EXPIRY_FLATTEN"
            else:
                try:
                    elapsed = _sessions_elapsed(p.opened_at, now)
                except SchedulerError:
                    alerts.append(f"CALENDAR_UNCOVERED:{ref}")
                    continue
                if elapsed < p.horizon_max_days:
                    continue
                reason = "HORIZON_REACHED"
            attempt = sum(1 for x in st.exits.values() if x.entry == ref)
            exit_ref = hashlib.sha256(f"{policy.digest()}|{ref}|EXIT|{attempt}".encode(
                "utf-8")).hexdigest()[:32]
            ledger._append(now, "EXIT_PROPOSED", track=p.track, reference=exit_ref,
                           session_date=day,
                           detail={"entry": ref, "units": str(p.units), "reason": reason,
                                   "bid": str(quote.bid), "authority": authority})
            exits.append(ExitProposal(exit_ref, ref, policy.digest(), p.track, p.canonical_id,
                                      p.etoro_instrument_id, p.units, reason, now,
                                      authority=authority))
        return self._finish(now, tuple(exits), alerts)

    def _protective_valid(self, now: datetime) -> bool:
        if self._protective is None:
            return False
        document, signature = self._protective
        try:
            grant = self._authority.check(document=document, signature=signature,
                                          subject_digest=protective_subject(self.policy), now=now)
        except GrantRefused:
            return False
        return (grant.kind == "autonomous_policy" and grant.issued_by == OWNER_PRINCIPAL
                and grant.broker == BROKER and grant.not_before >= self.policy.not_before)

    def incident_report(self) -> dict[str, Any]:
        """Owner-facing incident summary: what needs a human, and what to do (runbook R5)."""
        with self.ledger.transaction():
            now = self._now()
            st = self.ledger.state()
            policy_active = self.policy.active(now)
            grant_ok = policy_active and self._grant_valid(now)
            protective_ok = self._protective_valid(now)
        positions = _open_positions(st)

        def refs(items: Any, outcome: str | None) -> list[str]:
            return sorted(i.reference for i in items if i.outcome == outcome)

        report: dict[str, Any] = {
            "policy_digest": self.policy.digest(), "generated_at": now.isoformat(),
            "kill_switch": st.killed, "policy_active": policy_active,
            "grant_valid": grant_ok, "protective_exit_authority": protective_ok,
            "open_positions": [{"entry_reference": p.entry_reference, "canonical_id":
                                p.canonical_id, "units": str(p.units),
                                "stop_price": str(p.stop_price)} for p in positions],
            "pending_entries": refs(st.entries.values(), None),
            "pending_exits": refs(st.exits.values(), None),
            "unresolved_entries": refs(st.entries.values(), "UNRESOLVED"),
            "quarantined_entries": refs(st.entries.values(), "QUARANTINED"),
            "unresolved_exits": refs(st.exits.values(), "UNRESOLVED"),
            "quarantined_exits": refs(st.exits.values(), "QUARANTINED"),
            "unknown_quarantined_references": sorted(
                q for q in st.quarantined if q not in st.entries and q not in st.exits),
            "submission": SUBMISSION,
        }
        actions = []
        for ref in report["unresolved_entries"] + report["quarantined_entries"]:
            actions.append(f"Entry {ref}: look the order up in eToro Demo by its reference; "
                           "record the result as verified reconciliation evidence "
                           "(reconcile_unknown). A position may exist and is not exit-managed.")
        for ref in report["unresolved_exits"] + report["quarantined_exits"]:
            actions.append(f"Exit {ref}: confirm in eToro Demo whether the close executed; "
                           "record verified reconciliation evidence; close manually if still open.")
        for ref in report["unknown_quarantined_references"]:
            actions.append(f"Reference {ref} came only from a recovered anchor; check the broker "
                           "for any order or position carrying it.")
        if positions and not grant_ok and not protective_ok:
            actions.append("Open positions have no exit authority (policy expired or grant not "
                           "valid): close them manually in the eToro Demo UI, or sign a "
                           "protective-exit grant.")
        if st.killed:
            actions.append("Kill-switch engaged: new entries are blocked for this policy; a new "
                           "owner-signed policy is required to resume entries.")
        report["owner_actions"] = actions
        report["status"] = "ACTION_REQUIRED" if actions else "OK"
        return report

    def _finish(self, now: datetime, exits: tuple[ExitProposal, ...],
                alerts: list[str]) -> ExitPlan:
        # Record each alert code once per session so polling cannot grow the ledger.
        day = now.astimezone(NEW_YORK).date()
        logged = {json.loads(raw)["code"] for (raw,) in self.ledger._conn.execute(
            "SELECT detail FROM events WHERE event = 'ALERT' AND session_date = ?",
            (day.isoformat(),))}
        for code in dict.fromkeys(c[:200] for c in alerts):
            if code not in logged:
                self.ledger._append(now, "ALERT", session_date=day, detail={"code": code})
        return ExitPlan(exits, tuple(alerts))
