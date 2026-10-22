"""SD-070 normalized, versioned ``ResearchSignal`` contract.

Every research source (native strategies, TradingAgents, AI Hedge Fund /
BuffettAgent, day-trader methodologies, technical analysis) is reduced to this
one contract before the decision engine sees it. A signal is an opinion with
evidence; it can never carry order instructions or grant itself permission.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

SCHEMA = "sidedeck.research_signal.v1"
SOURCE_KINDS = frozenset({
    "NATIVE_STRATEGY", "TRADINGAGENTS", "AI_HEDGE_FUND", "DAY_TRADER_METHOD", "TECHNICAL_ANALYSIS",
})
AGENT_KINDS = frozenset({"TRADINGAGENTS", "AI_HEDGE_FUND", "DAY_TRADER_METHOD",
                         "TECHNICAL_ANALYSIS"})
DIRECTIONS = frozenset({"LONG", "SHORT", "NEUTRAL", "ABSTAIN"})
# Horizon bounds in trading days. DAY signals expire the same session.
TRACK_HORIZONS: dict[str, tuple[int, int]] = {
    "DAY": (0, 0), "SWING": (2, 15), "POSITION": (15, 180),
}
# Keys that would let a research source act on the market; refused outright.
_FORBIDDEN_KEY_PARTS = ("order", "execut", "permission", "approv", "authoriz", "quantity",
                        "size", "broker", "account", "leverage", "submit")
_ALLOWED_KEYS = frozenset({
    "schema", "canonical_id", "track", "source_kind", "source_id", "source_version",
    "horizon_min_days", "horizon_max_days", "direction", "evidence", "generated_at",
    "data_cutoff", "confidence", "calibration", "calibration_ref", "invalidation", "rationale",
})


class SignalError(ValueError):
    pass


@dataclass(frozen=True)
class EvidenceRef:
    kind: str
    reference: str
    sha256: str

    def __post_init__(self) -> None:
        if not self.kind.strip() or not self.reference.strip():
            raise SignalError("evidence needs a kind and reference")
        if len(self.sha256) != 64 or any(c not in "0123456789abcdef" for c in self.sha256):
            raise SignalError("evidence digest must be lower-case SHA-256 hex")


@dataclass(frozen=True)
class ResearchSignal:
    canonical_id: str
    track: str
    source_kind: str
    source_id: str
    source_version: str
    horizon_min_days: int
    horizon_max_days: int
    direction: str
    evidence: tuple[EvidenceRef, ...]
    generated_at: datetime
    data_cutoff: datetime
    invalidation: tuple[str, ...]
    rationale: str = ""
    confidence: Decimal | None = None
    calibration: str = "UNCALIBRATED"
    calibration_ref: str = ""
    schema: str = SCHEMA

    def __post_init__(self) -> None:
        if self.schema != SCHEMA:
            raise SignalError("unsupported signal schema")
        if not self.canonical_id.strip() or ":" not in self.canonical_id:
            raise SignalError("canonical instrument id required")
        if self.track not in TRACK_HORIZONS:
            raise SignalError(f"unknown track {self.track}")
        if self.source_kind not in SOURCE_KINDS:
            raise SignalError(f"unknown source kind {self.source_kind}")
        if not self.source_id.strip() or not self.source_version.strip():
            raise SignalError("versioned source identity required")
        low, high = TRACK_HORIZONS[self.track]
        if not low <= self.horizon_min_days <= self.horizon_max_days <= high:
            raise SignalError(f"horizon outside {self.track} bounds {low}-{high} days")
        if self.direction not in DIRECTIONS:
            raise SignalError(f"unknown direction {self.direction}")
        for stamp in (self.generated_at, self.data_cutoff):
            if stamp.tzinfo is None:
                raise SignalError("timestamps must be timezone-aware")
        if self.data_cutoff > self.generated_at:
            raise SignalError("data cutoff after generation time (look-ahead)")
        if self.direction in ("LONG", "SHORT"):
            if not self.evidence:
                raise SignalError("directional signals require evidence")
            if not self.invalidation or any(not c.strip() for c in self.invalidation):
                raise SignalError("directional signals require invalidation conditions")
        if self.confidence is not None and not (
            self.confidence.is_finite() and Decimal(0) <= self.confidence <= Decimal(1)
        ):
            raise SignalError("confidence must be within [0, 1]")
        if self.calibration not in ("UNCALIBRATED", "CALIBRATED"):
            raise SignalError("invalid calibration status")
        if self.calibration == "CALIBRATED" and not self.calibration_ref.strip():
            raise SignalError("calibrated confidence requires a calibration reference")

    @property
    def is_agent(self) -> bool:
        return self.source_kind in AGENT_KINDS

    @property
    def signal_id(self) -> str:
        data = asdict(self)
        data["generated_at"] = self.generated_at.astimezone(UTC).isoformat()
        data["data_cutoff"] = self.data_cutoff.astimezone(UTC).isoformat()
        payload = json.dumps(data, sort_keys=True, default=str, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()


def _forbidden(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in _FORBIDDEN_KEY_PARTS)


def _int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SignalError(f"{name} must be an integer")
    return int(value)


def normalize_signal(
    raw: Mapping[str, Any], *, now: datetime, source_kind: str, source_id: str,
) -> ResearchSignal:
    """Strictly convert an untrusted source payload into a ``ResearchSignal``.

    ``source_kind`` and ``source_id`` come from the adapter that invoked the source
    (a trusted channel), never from the payload. External payloads can never claim
    to be ``NATIVE_STRATEGY``: native signals are built in-process by SideDeck.
    """
    if now.tzinfo is None:
        raise SignalError("timezone-aware time required")
    if source_kind not in AGENT_KINDS:
        raise SignalError("only agent/method adapters may normalize external payloads")
    for key, trusted in (("source_kind", source_kind), ("source_id", source_id)):
        if key in raw and raw[key] != trusted:
            raise SignalError(f"payload {key} does not match the invoking adapter")
    bad = sorted(k for k in raw if _forbidden(str(k)))
    if bad:
        raise SignalError(f"research sources cannot carry execution fields: {bad}")
    unknown = sorted(set(map(str, raw)) - _ALLOWED_KEYS)
    if unknown:
        raise SignalError(f"unknown signal fields: {unknown}")
    try:
        generated = datetime.fromisoformat(str(raw["generated_at"]))
        cutoff = datetime.fromisoformat(str(raw["data_cutoff"]))
        confidence = raw.get("confidence")
        conf = None if confidence is None else Decimal(str(confidence))
        evidence = tuple(
            EvidenceRef(str(e["kind"]), str(e["reference"]), str(e["sha256"]))
            for e in raw.get("evidence", ())
        )
        signal = ResearchSignal(
            canonical_id=str(raw["canonical_id"]), track=str(raw["track"]),
            source_kind=source_kind, source_id=source_id,
            source_version=str(raw["source_version"]),
            horizon_min_days=_int(raw["horizon_min_days"], "horizon_min_days"),
            horizon_max_days=_int(raw["horizon_max_days"], "horizon_max_days"),
            direction=str(raw["direction"]), evidence=evidence, generated_at=generated,
            data_cutoff=cutoff, invalidation=tuple(str(c) for c in raw.get("invalidation", ())),
            rationale=str(raw.get("rationale", ""))[:2000], confidence=conf,
            calibration=str(raw.get("calibration", "UNCALIBRATED")),
            calibration_ref=str(raw.get("calibration_ref", "")),
            schema=str(raw.get("schema", SCHEMA)),
        )
    except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
        if isinstance(exc, SignalError):
            raise
        raise SignalError(f"malformed signal: {exc}") from exc
    if signal.generated_at > now:
        raise SignalError("signal generated in the future")
    return signal
