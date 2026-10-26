"""Offline eToro market-data contract and fail-closed fixture parsers.

This module deliberately has no HTTP client and never reads credentials.  It
turns the documented eToro data shapes into a reviewable request plan and
strict, provenance-bearing local records.  A future authenticated transport
must be implemented separately and explicitly authorized.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping


class EtoroMarketDataError(ValueError):
    """A malformed, ambiguous or economically unsafe market-data payload."""


SUPPORTED_SYMBOLS = ("SPY", "QQQ", "MSFT")
SEARCH_PATH = "/api/v1/market-data/search"
COVERAGE_PATH = "/api/v1/data/instruments/{instrumentId}/candles/coverage"
CANDLES_PATH = "/api/v1/data/instruments/{instrumentId}/candles"
LOCAL_PAGE_LIMIT = 2_000
_SYMBOL = re.compile(r"^[A-Z][A-Z0-9.-]{0,11}$")


@dataclass(frozen=True)
class RequestSpec:
    """An owner-reviewable request without credentials or executable transport."""

    purpose: str
    path: str
    query: tuple[tuple[str, str], ...]
    instrument: str
    requires_owner_authorization: bool = True


@dataclass(frozen=True)
class Candle:
    instrument_id: int
    symbol: str
    interval: str
    side: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None


def _symbol(symbol: str) -> str:
    value = symbol.strip().upper()
    if value not in SUPPORTED_SYMBOLS or not _SYMBOL.fullmatch(value):
        raise EtoroMarketDataError("symbol is outside the bounded research universe")
    return value


def _instrument_id(value: Any) -> int:
    if isinstance(value, bool):
        raise EtoroMarketDataError("instrument ID must be a positive integer")
    try:
        result = int(value)
    except (TypeError, ValueError):
        raise EtoroMarketDataError("instrument ID must be a positive integer") from None
    if result <= 0 or str(result) != str(value).strip():
        raise EtoroMarketDataError("instrument ID must be a positive integer")
    return result


def _time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise EtoroMarketDataError("candle timestamp must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise EtoroMarketDataError("candle timestamp is invalid") from None
    if parsed.tzinfo is None:
        raise EtoroMarketDataError("candle timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def _decimal(value: Any, field: str, *, positive: bool = True) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise EtoroMarketDataError(f"{field} must be a decimal") from None
    if not result.is_finite() or (positive and result <= 0):
        raise EtoroMarketDataError(f"{field} must be finite and positive")
    return result


def request_plan() -> tuple[RequestSpec, ...]:
    """Return the exact bounded plan; this function performs no requests."""

    plan: list[RequestSpec] = []
    for symbol in SUPPORTED_SYMBOLS:
        plan.append(RequestSpec(
            "instrument discovery", SEARCH_PATH,
            (("internalSymbolFull", symbol),), symbol,
        ))
    # IDs are intentionally placeholders.  Coverage and candle requests may
    # only be materialized after a response proves an exact symbol identity.
    for symbol in SUPPORTED_SYMBOLS:
        plan.append(RequestSpec(
            "five-minute coverage", COVERAGE_PATH.replace("{instrumentId}", "<verified-id>"),
            (), symbol,
        ))
    for symbol in SUPPORTED_SYMBOLS:
        plan.append(RequestSpec(
            "bounded five-minute sample", CANDLES_PATH.replace("{instrumentId}", "<verified-id>"),
            (("interval", "5m"), ("side", "both"), ("limit", str(LOCAL_PAGE_LIMIT))), symbol,
        ))
    return tuple(plan)


def parse_instrument_search(payload: Mapping[str, Any], symbol: str) -> int:
    """Resolve one exact stock identity from a fixture; reject ambiguity."""

    expected = _symbol(symbol)
    rows = payload.get("results", payload.get("items", payload.get("data")))
    if not isinstance(rows, list):
        raise EtoroMarketDataError("instrument search result list is missing")
    matches = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        candidate = str(row.get("internalSymbolFull", row.get("symbol", ""))).upper()
        if candidate == expected:
            matches.append(row)
    if len(matches) != 1:
        raise EtoroMarketDataError("instrument identity is missing or ambiguous")
    row = matches[0]
    return _instrument_id(row.get("instrumentId", row.get("internalInstrumentId")))


def parse_coverage(payload: Mapping[str, Any], *, instrument_id: int, symbol: str) -> dict[str, Any]:
    """Normalize documented coverage without claiming entitlement or adjustment."""

    expected_id = _instrument_id(instrument_id)
    expected_symbol = _symbol(symbol)
    if _instrument_id(payload.get("instrumentId")) != expected_id:
        raise EtoroMarketDataError("coverage instrument identity mismatch")
    if str(payload.get("symbol", "")).upper() != expected_symbol:
        raise EtoroMarketDataError("coverage symbol identity mismatch")
    intervals = payload.get("intervals")
    if not isinstance(intervals, list):
        raise EtoroMarketDataError("coverage intervals are missing")
    normalized = []
    for item in intervals:
        if not isinstance(item, Mapping) or not isinstance(item.get("interval"), str):
            raise EtoroMarketDataError("coverage interval is malformed")
        count = item.get("candles")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise EtoroMarketDataError("coverage candle count is invalid")
        normalized.append({
            "interval": item["interval"],
            "first_candle": item.get("firstCandle"),
            "last_candle": item.get("lastCandle"),
            "candles": count,
            "loaded_at": item.get("loadedAt"),
        })
    return {
        "instrument_id": expected_id,
        "symbol": expected_symbol,
        "intervals": normalized,
        "basis": "ETORO_DOCUMENTED_COVERAGE_UNVERIFIED_ENTITLEMENT",
    }


def _display_symbol_matches(value: Any, expected: str, *, empty: bool) -> bool:
    if value is None:
        return empty
    if not isinstance(value, str):
        return False
    # eToro's display symbol is commonly ``AAPL/USD``; identity remains the
    # separately verified instrument ID plus the exact requested ticker.
    return value.upper().split("/", 1)[0] == expected


def _parse_price_row(row: Mapping[str, Any], *, expected_id: int, expected_symbol: str,
                     side: str) -> Candle:
    values = {name: _decimal(row.get(name), name) for name in ("open", "high", "low", "close")}
    if values["high"] < max(values["open"], values["close"]) or values["low"] > min(values["open"], values["close"]):
        raise EtoroMarketDataError("candle OHLC bounds are inconsistent")
    volume = None if row.get("volume") is None else _decimal(row.get("volume"), "volume", positive=False)
    return Candle(expected_id, expected_symbol, "5m", side, _time(row.get("time")), **values, volume=volume)


def parse_candles(payload: Mapping[str, Any], *, instrument_id: int, symbol: str) -> tuple[Candle, ...]:
    """Parse a bounded fixture page, normalizing newest-first pages to ascending.

    For ``side=both`` the documented verbose response is represented as one row
    with ``bid`` and ``ask`` OHLC objects.  The canonical output contains one
    ``Candle`` per side and timestamp; this prevents bid/ask values from being
    accidentally treated as one synthetic price series.
    """

    expected_id = _instrument_id(instrument_id)
    expected_symbol = _symbol(symbol)
    if _instrument_id(payload.get("instrumentId")) != expected_id:
        raise EtoroMarketDataError("candle instrument identity mismatch")
    rows = payload.get("results")
    if not isinstance(rows, list) or len(rows) > LOCAL_PAGE_LIMIT:
        raise EtoroMarketDataError("candle page exceeds the local bounded limit")
    if not _display_symbol_matches(payload.get("symbol"), expected_symbol, empty=not rows):
        raise EtoroMarketDataError("candle display symbol identity mismatch")
    if payload.get("interval") != "5m" or payload.get("side") not in {"bid", "ask", "both"}:
        raise EtoroMarketDataError("only explicit five-minute bid/ask candle pages are accepted")
    parsed: list[Candle] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise EtoroMarketDataError("candle row is malformed")
        if payload["side"] == "both":
            for side in ("bid", "ask"):
                side_row = row.get(side)
                if not isinstance(side_row, Mapping):
                    raise EtoroMarketDataError("side=both requires bid and ask OHLC objects")
                side_row = dict(side_row)
                side_row["time"] = row.get("time")
                parsed.append(_parse_price_row(side_row, expected_id=expected_id,
                                               expected_symbol=expected_symbol, side=side))
        else:
            parsed.append(_parse_price_row(row, expected_id=expected_id,
                                           expected_symbol=expected_symbol, side=str(payload["side"])))
    timestamps = [(c.timestamp, c.side) for c in parsed]
    if len(timestamps) != len(set(timestamps)):
        raise EtoroMarketDataError("candle timestamps must be unique per side")
    return tuple(sorted(parsed, key=lambda c: (c.timestamp, c.side)))


def provenance(payload: Mapping[str, Any]) -> dict[str, str]:
    """Hash an exact fixture payload; never infer source authenticity."""

    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return {
        "source": "etoro",
        "evidence": "FIXTURE_ONLY_UNVERIFIED_ENTITLEMENT",
        "payload_sha256": hashlib.sha256(encoded).hexdigest(),
        "adjustment": "UNVERIFIED",
        "volume_semantics": "UNVERIFIED",
        "corporate_actions": "UNVERIFIED",
    }
