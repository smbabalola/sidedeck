"""SD-074 authenticated-input boundary for the autonomous Demo runtime (offline).

Closes the SD-063 review residuals R1, R2 and R4: research signals, broker quotes and fill
evidence reach the policy runtime only inside envelopes sealed (HMAC-SHA256) by a registered
source whose **role** permits that kind of input. Producers are SideDeck's own adapters (the
in-process native strategy runner, the broker quote adapter, the broker reconciliation adapter);
each holds only its own key. Nothing a caller writes into a payload can claim authentication:
self-asserted fields such as ``authenticated``/``verified``/``source_id`` are refused, and the
envelope's source is the only identity used.

Rules (all fail closed):

* **Registry:** unique source ids, keys >= 32 bytes, one role each. Roles map to kinds:
  ``native_strategy_runner`` -> signal (may emit NATIVE_STRATEGY), ``agent_adapter`` -> signal
  (agent kinds only, via ``normalize_signal``), ``broker_quotes`` -> quote,
  ``broker_reconciliation`` -> fill.
* **Envelope:** constant-time MAC check over the canonical JSON; issued_at tz-aware, not in the
  future (5 s skew), within the per-kind maximum age; nonce single-use, persisted in SQLite so a
  replay is refused across restarts and workers.
* **Conversion:** strict payload shapes; Decimal parsing; quote bid <= ask; a fill carries the
  broker order id and the SHA-256 of the broker order lookup it came from.

This module makes no network request and holds no broker credentials. The broker adapters that
will seal real quotes and fills (after their own authenticated TLS reads) belong to SD-074's
transport integration, which waits for the SD-058 pilot and re-lock.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sidedeck.application.sd063_autonomous_demo_policy import (
    AutonomousDemoRuntime, EntryProposal, EntryQuote, ExitPlan, ExitQuote, FillEvidence,
    PolicyLedger, Refusal, _new_fill_evidence,
)
from sidedeck.application.sd070_research_signal import (
    EvidenceRef, ResearchSignal, SignalError, normalize_signal,
)
from sidedeck.application.sd071_decision_engine import MarketContext, StrategyAdmission

ROLES = {"native_strategy_runner": "signal", "agent_adapter": "signal",
         "broker_quotes": "quote", "broker_reconciliation": "fill"}
MAX_AGE = {"signal": timedelta(hours=24), "quote": timedelta(seconds=60),
           "fill": timedelta(days=7)}
CLOCK_SKEW = timedelta(seconds=5)
MIN_KEY_BYTES = 32
_SELF_CLAIMS = ("authenticated", "verified", "trusted", "signature", "mac", "source_id",
                "source_role")
_NONCE = re.compile(r"[0-9a-f]{32}")
_HEX64 = re.compile(r"[0-9a-f]{64}")


class InputRefused(PermissionError):
    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class TrustedSource:
    source_id: str
    role: str
    key: bytes = field(repr=False)

    @property
    def kind(self) -> str:
        return ROLES[self.role]


class SourceRegistry:
    def __init__(self, sources: Sequence[TrustedSource]) -> None:
        ids = [s.source_id for s in sources]
        if len(set(ids)) != len(ids):
            raise InputRefused("duplicate source id")
        for s in sources:
            if s.role not in ROLES:
                raise InputRefused(f"unknown source role {s.role}")
            if not isinstance(s.key, bytes) or len(s.key) < MIN_KEY_BYTES:
                raise InputRefused("source keys must be at least 32 bytes")
            if not isinstance(s.source_id, str) or not s.source_id.strip():
                raise InputRefused("source id required")
        self._sources = {s.source_id: s for s in sources}

    def get(self, source_id: str) -> TrustedSource | None:
        return self._sources.get(source_id)


@dataclass(frozen=True)
class Envelope:
    kind: str
    source_id: str
    issued_at: str
    nonce: str
    payload: Mapping[str, Any]
    mac: str

    def canonical(self) -> bytes:
        return _canonical(self.kind, self.source_id, self.issued_at, self.nonce, self.payload)


def _canonical(kind: str, source_id: str, issued_at: str, nonce: str,
               payload: Mapping[str, Any]) -> bytes:
    return json.dumps({"kind": kind, "source_id": source_id, "issued_at": issued_at,
                       "nonce": nonce, "payload": payload},
                      sort_keys=True, separators=(",", ":")).encode("utf-8")


class SourceSigner:
    """Held by one producer adapter; seals what that adapter observed."""

    def __init__(self, source: TrustedSource, clock: Callable[[], datetime] = _utc_now) -> None:
        self._source, self._clock = source, clock

    def seal(self, payload: Mapping[str, Any]) -> Envelope:
        issued = self._clock().astimezone(timezone.utc).isoformat()
        nonce = secrets.token_hex(16)
        kind = self._source.kind
        body = json.loads(json.dumps(payload))          # plain JSON values only
        mac = hmac.new(self._source.key, _canonical(kind, self._source.source_id, issued,
                                                    nonce, body), hashlib.sha256).hexdigest()
        return Envelope(kind, self._source.source_id, issued, nonce, body, mac)


class NonceStore:
    """Persistent single-use nonces (shared by workers through one SQLite file)."""

    def __init__(self, path: Path) -> None:
        self._conn = sqlite3.connect(str(path), isolation_level=None, timeout=10)
        self._conn.execute("CREATE TABLE IF NOT EXISTS nonces (source_id TEXT NOT NULL, "
                           "nonce TEXT NOT NULL, seen_at TEXT NOT NULL, "
                           "PRIMARY KEY (source_id, nonce))")

    def consume(self, source_id: str, nonce: str, at: datetime) -> None:
        try:
            self._conn.execute("INSERT INTO nonces VALUES (?, ?, ?)",
                               (source_id, nonce, at.isoformat()))
        except sqlite3.IntegrityError:
            raise InputRefused("replayed envelope (nonce already used)") from None

    def close(self) -> None:
        self._conn.close()


@dataclass(frozen=True)
class BrokerQuote:
    canonical_id: str
    bid: Decimal
    ask: Decimal
    quote_time: datetime
    source_id: str

    def entry(self) -> EntryQuote:
        return EntryQuote(self.canonical_id, self.ask, self.quote_time)

    def exit(self) -> ExitQuote:
        return ExitQuote(self.canonical_id, self.bid, self.quote_time)


def _dec(value: Any, name: str) -> Decimal:
    if not isinstance(value, str):
        raise InputRefused(f"{name} must be a decimal string")
    try:
        d = Decimal(value)
    except InvalidOperation:
        raise InputRefused(f"{name} is not a decimal") from None
    if not d.is_finite():
        raise InputRefused(f"{name} must be finite")
    return d


def _time(value: Any, name: str) -> datetime:
    try:
        t = datetime.fromisoformat(str(value))
    except ValueError:
        raise InputRefused(f"{name} is not a timestamp") from None
    if t.tzinfo is None:
        raise InputRefused(f"{name} must be timezone-aware")
    return t


def _exact(payload: Mapping[str, Any], keys: set[str]) -> None:
    if set(payload) != keys:
        raise InputRefused(f"payload must contain exactly {sorted(keys)}")


class InputVerifier:
    def __init__(self, registry: SourceRegistry, nonces: NonceStore, *,
                 clock: Callable[[], datetime] = _utc_now) -> None:
        self._registry, self._nonces, self._clock = registry, nonces, clock

    def verify(self, envelope: Envelope, kind: str) -> tuple[TrustedSource, dict[str, Any]]:
        if not isinstance(envelope, Envelope) or envelope.kind != kind:
            raise InputRefused(f"expected a {kind} envelope")
        source = self._registry.get(envelope.source_id)
        if source is None or source.kind != kind:
            raise InputRefused("envelope source is not registered for this input kind")
        expected = hmac.new(source.key, envelope.canonical(), hashlib.sha256).hexdigest()
        if not isinstance(envelope.mac, str) or not hmac.compare_digest(expected, envelope.mac):
            raise InputRefused("envelope MAC does not verify")
        if not isinstance(envelope.nonce, str) or not _NONCE.fullmatch(envelope.nonce):
            raise InputRefused("envelope nonce is malformed")
        now = self._clock().astimezone(timezone.utc)
        issued = _time(envelope.issued_at, "issued_at")
        if issued > now + CLOCK_SKEW or now - issued > MAX_AGE[kind]:
            raise InputRefused("envelope is stale or from the future")
        payload = dict(envelope.payload)
        claims = sorted(k for k in payload if any(c in str(k).lower() for c in _SELF_CLAIMS))
        if claims:
            raise InputRefused(f"payload cannot assert its own authentication: {claims}")
        self._nonces.consume(source.source_id, envelope.nonce, now)
        return source, payload

    def signal(self, envelope: Envelope) -> ResearchSignal:
        source, payload = self.verify(envelope, "signal")
        try:
            if source.role == "native_strategy_runner":
                if payload.get("source_kind") != "NATIVE_STRATEGY":
                    raise InputRefused("the native runner emits NATIVE_STRATEGY signals only")
                return ResearchSignal(
                    canonical_id=str(payload["canonical_id"]), track=str(payload["track"]),
                    source_kind="NATIVE_STRATEGY", source_id=str(payload["strategy_id"]),
                    source_version=str(payload["strategy_version"]),
                    horizon_min_days=int(payload["horizon_min_days"]),
                    horizon_max_days=int(payload["horizon_max_days"]),
                    direction=str(payload["direction"]),
                    evidence=tuple(EvidenceRef(str(e["kind"]), str(e["reference"]),
                                               str(e["sha256"])) for e in payload["evidence"]),
                    generated_at=_time(payload["generated_at"], "generated_at"),
                    data_cutoff=_time(payload["data_cutoff"], "data_cutoff"),
                    invalidation=tuple(str(c) for c in payload["invalidation"]))
            kind = payload.pop("source_kind", None)
            if kind == "NATIVE_STRATEGY":
                raise InputRefused("only the native strategy runner may emit NATIVE_STRATEGY")
            return normalize_signal(payload, now=self._clock(), source_kind=str(kind),
                                    source_id=source.source_id)
        except (KeyError, TypeError, ValueError, SignalError) as exc:
            if isinstance(exc, InputRefused):
                raise
            raise InputRefused(f"malformed signal payload: {type(exc).__name__}") from None

    def quote(self, envelope: Envelope) -> BrokerQuote:
        source, payload = self.verify(envelope, "quote")
        _exact(payload, {"canonical_id", "bid", "ask", "quote_time"})
        bid, ask = _dec(payload["bid"], "bid"), _dec(payload["ask"], "ask")
        if not (Decimal(0) < bid <= ask):
            raise InputRefused("quote needs 0 < bid <= ask")
        return BrokerQuote(str(payload["canonical_id"]), bid, ask,
                           _time(payload["quote_time"], "quote_time"), source.source_id)

    def fill(self, envelope: Envelope) -> FillEvidence:
        source, payload = self.verify(envelope, "fill")
        _exact(payload, {"reference", "outcome", "units", "price", "filled_at",
                         "broker_order_id", "lookup_sha256"})
        if not isinstance(payload["lookup_sha256"], str) or \
                not _HEX64.fullmatch(payload["lookup_sha256"]):
            raise InputRefused("fill evidence needs the broker order lookup digest")
        try:
            return _new_fill_evidence(
                reference=payload["reference"], outcome=payload["outcome"],
                units=_dec(payload["units"], "units"), price=_dec(payload["price"], "price"),
                at=_time(payload["filled_at"], "filled_at"), source_id=source.source_id,
                broker_order_id=str(payload["broker_order_id"]),
                lookup_sha256=payload["lookup_sha256"])
        except PermissionError as exc:
            if isinstance(exc, InputRefused):
                raise
            raise InputRefused(str(exc)) from None


class AuthenticatedRuntime:
    """The SD-063 runtime driven only by verified envelopes (no caller-built prices/fills)."""

    def __init__(self, runtime: AutonomousDemoRuntime, verifier: InputVerifier) -> None:
        self.runtime, self._verifier = runtime, verifier

    @property
    def ledger(self) -> PolicyLedger:
        return self.runtime.ledger

    def _quotes(self, envelopes: Sequence[Envelope]) -> dict[str, BrokerQuote]:
        quotes: dict[str, BrokerQuote] = {}
        for env in envelopes:
            q = self._verifier.quote(env)
            if q.canonical_id in quotes:
                raise InputRefused("two quotes for one instrument")
            quotes[q.canonical_id] = q
        return quotes

    def propose_entry(
        self, *, track: str, signals: Sequence[Envelope],
        admissions: Sequence[StrategyAdmission], research: MarketContext,
        quote: Envelope, marks: Sequence[Envelope],
    ) -> EntryProposal | Refusal:
        """``research`` supplies ATR, sector, correlations and broker eligibility from the
        research pipeline; its price and price time are replaced by the verified quote."""
        try:
            verified = [self._verifier.signal(e) for e in signals]
            q = self._verifier.quote(quote)
            mark_quotes = self._quotes(marks)
        except InputRefused as exc:
            return Refusal((f"INPUT_REFUSED:{exc}",))
        if q.canonical_id != research.canonical_id:
            return Refusal(("QUOTE_INSTRUMENT_MISMATCH",))
        market = MarketContext(research.canonical_id, q.ask, q.quote_time, research.atr,
                               research.sector, research.session_open,
                               research.execution_eligible, research.correlations)
        return self.runtime.propose_entry(
            track=track, signals=verified, admissions=admissions, market=market,
            quote=q.entry(), marks={c: m.bid for c, m in mark_quotes.items()})

    def plan_exits(self, *, bids: Sequence[Envelope]) -> ExitPlan:
        try:
            quotes = self._quotes(bids)
        except InputRefused as exc:
            return ExitPlan((), (f"INPUT_REFUSED:{exc}",))
        return self.runtime.plan_exits(bids={c: q.exit() for c, q in quotes.items()})

    def resolve(self, fill: Envelope) -> None:
        self.ledger.resolve(self._verifier.fill(fill))

    def reconcile_unknown(self, fill: Envelope) -> None:
        self.ledger.reconcile_unknown(self._verifier.fill(fill))
