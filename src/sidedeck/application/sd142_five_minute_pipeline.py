"""Provider-neutral, offline five-minute quote-bar validation (SD-142).

This module consumes already acquired local rows. It performs no provider I/O and
cannot promote fixture or unverified-license data to strategy admission.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Protocol, Sequence

from sidedeck.application.sd068_track_scheduler import session_for
from sidedeck.application.sd069_day_trader_methods import IntradayBar
from sidedeck.application.sd119_etoro_market_data import EtoroMarketDataError, parse_candles, provenance
from sidedeck.application.sd074_trusted_inputs import Envelope, SourceSigner

STEP = timedelta(minutes=5)
FIELDS = ("open", "high", "low", "close")
_SHA256 = re.compile(r"[0-9a-f]{64}")


class FiveMinuteDataError(ValueError):
    """Input is incomplete, inconsistent, stale or lacks required evidence."""


@dataclass(frozen=True)
class FiveMinuteBundle:
    bars: tuple[IntradayBar, ...]
    report: Mapping[str, Any]
    provenance_envelope: Envelope


class FiveMinuteProvider(Protocol):
    """Local fixture/provider parser contract. Implementations must not acquire data here."""

    source_id: str

    def normalize(self, payload: Any, *, symbol: str,
                  instrument_id: int) -> Sequence[Mapping[str, Any]]: ...


class EtoroFiveMinuteFixtureProvider:
    """Normalize local eToro candle fixtures without asserting entitlement or adjustments.

    The SD-119 parser verifies response identity and bid/ask structure. Since its
    evidence is explicitly unverified, downstream SD-142 admission rejects these
    rows until independently verified licensing, mapping and action metadata exist.
    """

    source_id = "etoro"

    def normalize(self, payload: Any, *, symbol: str,
                  instrument_id: int) -> Sequence[Mapping[str, Any]]:
        if not isinstance(payload, Mapping) or payload.get("side") != "both":
            raise FiveMinuteDataError("eToro fixture requires an explicit bid/ask candle page")
        try:
            candles = parse_candles(payload, instrument_id=instrument_id, symbol=symbol)
            source_hash = provenance(payload)["payload_sha256"]
        except EtoroMarketDataError as exc:
            raise FiveMinuteDataError("eToro fixture identity or candle validation failed") from exc
        by_time: dict[datetime, dict[str, Any]] = {}
        for candle in candles:
            sides = by_time.setdefault(candle.timestamp, {})
            sides[candle.side] = candle
        normalized: list[Mapping[str, Any]] = []
        for stamp, sides in sorted(by_time.items()):
            bid, ask = sides.get("bid"), sides.get("ask")
            if bid is None or ask is None or bid.volume is None or ask.volume is None \
                    or bid.volume != ask.volume:
                raise FiveMinuteDataError("eToro fixture requires matching bid/ask volume")
            row: dict[str, Any] = {"start": stamp.isoformat(), "volume": str(bid.volume)}
            for name in FIELDS:
                row[f"bid_{name}"] = str(getattr(bid, name))
                row[f"ask_{name}"] = str(getattr(ask, name))
            row.update({
                "source_id": self.source_id, "source_hash": source_hash,
                "adjustment_basis": "UNVERIFIED",
                "corporate_actions_asof": "UNVERIFIED",
                "mapping_status": "UNVERIFIED", "mapping_asof": "UNVERIFIED",
                "entitlement_status": "UNVERIFIED", "mapped_symbol": symbol,
                "mapped_instrument_id": str(instrument_id),
            })
            normalized.append(row)
        return normalized


def _decimal(value: Any, label: str) -> Decimal:
    if isinstance(value, bool):
        raise FiveMinuteDataError(f"{label} must be a decimal number")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise FiveMinuteDataError(f"{label} must be a decimal number") from None
    if not result.is_finite():
        raise FiveMinuteDataError(f"{label} must be finite")
    return result


def _stamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise FiveMinuteDataError("bar start must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise FiveMinuteDataError("bar start must be an ISO timestamp") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise FiveMinuteDataError("bar start must include a timezone")
    return parsed.astimezone(UTC)


def validate_five_minute_session(
    rows: Sequence[Mapping[str, Any]], *, symbol: str, instrument_id: int,
    session_day: date, ingested_at: datetime, signer: SourceSigner,
    max_ingestion_lag: timedelta = timedelta(minutes=2),
) -> FiveMinuteBundle:
    """Validate exactly one complete XNYS session of normalized bid/ask bars.

    Each row carries ``start``, bid/ask OHLC, ``volume``, ``adjustment_basis``,
    ``corporate_actions_asof``, ``mapping_status``, ``mapping_asof`` and source
    provenance fields. Output midpoint bars are research-only and never executable.
    """
    if not symbol or symbol != symbol.upper() or not isinstance(instrument_id, int) \
            or isinstance(instrument_id, bool) or instrument_id <= 0:
        raise FiveMinuteDataError("exact uppercase symbol and positive instrument ID required")
    if ingested_at.tzinfo is None or ingested_at.utcoffset() is None:
        raise FiveMinuteDataError("ingestion time must be timezone-aware")
    if max_ingestion_lag < timedelta(0):
        raise FiveMinuteDataError("maximum ingestion lag cannot be negative")
    session = session_for(session_day)
    if session is None:
        raise FiveMinuteDataError("requested date is not a verified exchange session")
    expected: list[datetime] = []
    stamp = session.open_utc
    while stamp + STEP <= session.close_utc:
        expected.append(stamp)
        stamp += STEP
    if not rows:
        raise FiveMinuteDataError("empty session")
    if signer.role != "research_pipeline":
        raise FiveMinuteDataError("five-minute provenance requires a research source signer")

    parsed: dict[datetime, IntradayBar] = {}
    source_contract: tuple[str, ...] | None = None
    canonical_rows: list[dict[str, str]] = []
    for row in rows:
        try:
            start = _stamp(row["start"])
            if start in parsed:
                raise FiveMinuteDataError("duplicate five-minute timestamp")
            if start not in set(expected):
                raise FiveMinuteDataError("bar is outside the exchange session grid")
            if start + STEP > ingested_at.astimezone(UTC):
                raise FiveMinuteDataError("future or incomplete five-minute bar")
            sides: dict[str, dict[str, Decimal]] = {}
            for side in ("bid", "ask"):
                values = {field: _decimal(row[f"{side}_{field}"], f"{side}_{field}")
                          for field in FIELDS}
                volume = _decimal(row["volume"], "volume")
                if min(values.values()) <= 0 or volume < 0 \
                        or values["high"] < max(values["open"], values["close"]) \
                        or values["low"] > min(values["open"], values["close"]) \
                        or values["high"] < values["low"]:
                    raise FiveMinuteDataError(f"invalid {side} OHLC or volume")
                sides[side] = values
            for field in FIELDS:
                if sides["bid"][field] > sides["ask"][field]:
                    raise FiveMinuteDataError("bid exceeds ask")
            raw_provenance = (row.get("source_id"), row.get("source_hash"),
                          row.get("adjustment_basis"), row.get("corporate_actions_asof"),
                          row.get("mapping_status"), row.get("mapping_asof"),
                          row.get("entitlement_status"), row.get("mapped_symbol"),
                          row.get("mapped_instrument_id"))
            if any(not isinstance(value, str) or not value.strip() for value in raw_provenance):
                raise FiveMinuteDataError("source, adjustment, mapping and entitlement provenance required")
            provenance = tuple(str(value) for value in raw_provenance)
            if not _SHA256.fullmatch(provenance[1]):
                raise FiveMinuteDataError("source content hash must be SHA-256")
            if provenance[4] != "VERIFIED" or provenance[6] != "VERIFIED":
                raise FiveMinuteDataError("instrument mapping and data entitlement must be verified")
            if provenance[7] != symbol or provenance[8] != str(instrument_id):
                raise FiveMinuteDataError("point-in-time mapping does not match requested instrument")
            mapping_asof, actions_asof = _stamp(provenance[5]), _stamp(provenance[3])
            if mapping_asof > start or actions_asof > start:
                raise FiveMinuteDataError("mapping or adjustment evidence is future-dated")
            if source_contract is None:
                source_contract = provenance
            elif source_contract != provenance:
                raise FiveMinuteDataError("mixed provenance contract within one bundle")
            mid = {field: (sides["bid"][field] + sides["ask"][field]) / 2
                   for field in FIELDS}
            parsed[start] = IntradayBar(start, mid["open"], mid["high"], mid["low"],
                                        mid["close"], volume)
            canonical_rows.append({"start": start.isoformat(), **{
                f"{side}_{field}": str(sides[side][field])
                for side in ("bid", "ask") for field in FIELDS
            }, "volume": str(volume)})
        except KeyError as exc:
            raise FiveMinuteDataError(f"missing required row field {exc.args[0]}") from None
    ordered = tuple(parsed[key] for key in sorted(parsed))
    if tuple(parsed) != tuple(sorted(parsed)):
        # Input order itself is part of the provider contract; do not silently sort.
        raise FiveMinuteDataError("bars must be supplied in timestamp order")
    if tuple(parsed) != tuple(expected):
        missing = sorted(set(expected) - set(parsed))
        raise FiveMinuteDataError(f"session has missing bars ({len(missing)} missing)")
    last_complete = session.close_utc
    lag = ingested_at.astimezone(UTC) - last_complete
    if lag < timedelta(0) or lag > max_ingestion_lag:
        raise FiveMinuteDataError("session bundle is future-dated or stale")
    if source_contract is None:
        raise FiveMinuteDataError("session has no source provenance")
    if signer.source_id != source_contract[0]:
        raise FiveMinuteDataError("provenance signer does not match the declared source")
    canonical = json.dumps({"symbol": symbol, "instrument_id": instrument_id,
                            "session": session_day.isoformat(), "source": source_contract,
                            "rows": canonical_rows}, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    report = {
        "schema": "sidedeck-provider-neutral-five-minute/1", "symbol": symbol,
        "instrument_id": instrument_id, "session": session_day.isoformat(),
        "session_open_utc": session.open_utc.isoformat(),
        "session_close_utc": session.close_utc.isoformat(), "early_close": session.early_close,
        "bars": len(ordered), "expected_bars": len(expected),
        "source_id": source_contract[0], "source_hash": source_contract[1],
        "adjustment_basis": source_contract[2], "corporate_actions_asof": source_contract[3],
        "mapping_status": source_contract[4], "mapping_asof": source_contract[5],
        "entitlement_status": source_contract[6], "mapped_symbol": source_contract[7],
        "mapped_instrument_id": source_contract[8],
        "ingested_at_utc": ingested_at.astimezone(UTC).isoformat(),
        "ingestion_lag_seconds": int(lag.total_seconds()), "data_version_sha256": digest,
        "price_basis": "BID_ASK_MIDPOINT_RESEARCH_ONLY",
        "strategy_admission_eligible": False, "broker_execution": "DISABLED",
    }
    envelope = signer.seal(report)
    return FiveMinuteBundle(ordered, report, envelope)


def ingest_provider_fixture(provider: FiveMinuteProvider, payload: Any, *, symbol: str,
                            instrument_id: int, session_day: date, ingested_at: datetime,
                            signer: SourceSigner,
                            max_ingestion_lag: timedelta = timedelta(minutes=2)
                            ) -> FiveMinuteBundle:
    """Normalize one local fixture through a provider plug-in, then validate and seal it."""
    if provider.source_id != signer.source_id:
        raise FiveMinuteDataError("provider parser and provenance signer identities differ")
    try:
        rows = provider.normalize(payload, symbol=symbol, instrument_id=instrument_id)
    except Exception as exc:
        raise FiveMinuteDataError("provider fixture parser refused the payload") from exc
    return validate_five_minute_session(
        rows, symbol=symbol, instrument_id=instrument_id, session_day=session_day,
        ingested_at=ingested_at, signer=signer, max_ingestion_lag=max_ingestion_lag,
    )


def coverage_report(bundles: Sequence[FiveMinuteBundle]) -> dict[str, Any]:
    """Render an auditable compact report; fixture provenance remains explicit."""
    return {"schema": "sidedeck-five-minute-coverage/1", "sessions": [dict(b.report)
            for b in bundles], "session_count": len(bundles),
            "strategy_admission_eligible": False, "broker_execution": "DISABLED"}
