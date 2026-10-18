"""Credential-free, read-only eToro market-data boundary.

The client accepts an injected transport so CI never contacts eToro. It has
no trading imports or methods, a fixed official host, and no Yahoo fallback.
Live coverage remains unverified until the owner authorises a read-only GET.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import re
import time
from typing import Any, Literal, Mapping, Protocol, cast
from uuid import UUID, uuid4

from .instruments import get_instrument_by_id

ETORO_BASE_URL = "https://public-api.etoro.com/api/v1"
DAILY_INTERVAL = "OneDay"
MAX_DAILY_CANDLES = 1000
MAX_RESPONSE_BYTES = 2_000_000
APPROVED_TICKERS = frozenset({"AAPL", "MSFT", "SPY", "QQQ"})


class EtoroDataError(ValueError):
    """A response cannot be used as a verified market-data observation."""


class EtoroAccessBlocked(RuntimeError):
    """An authenticated request requires explicit owner approval."""


class ReadOnlyMarketDataTransport(Protocol):
    def get(self, path: str, params: Mapping[str, str], request_id: UUID) -> tuple[int, Mapping[str, str], bytes]: ...


@dataclass(frozen=True)
class MarketDataReadCapability:
    """Non-secret capability marker; it cannot authorize trading endpoints."""

    scope: Literal["market-data-read"] = "market-data-read"
    token_id: UUID = field(default_factory=uuid4)


@dataclass(frozen=True)
class EtoroInstrument:
    instrument_id: int
    ticker: str
    asset_type: Literal["EQUITY", "ETF"]
    venue: str
    currency: str = "USD"
    leveraged: bool = False
    inverse: bool = False

    def validate(self) -> "EtoroInstrument":
        if self.ticker not in APPROVED_TICKERS:
            raise EtoroDataError("instrument is outside the approved SideDeck universe")
        if self.currency != "USD" or self.leveraged or self.inverse:
            raise EtoroDataError("instrument is not an unleveraged USD instrument")
        expected = get_instrument_by_id(f"US:{self.ticker}")
        if expected.asset_type != self.asset_type:
            raise EtoroDataError("eToro instrument type does not match SideDeck")
        return self


@dataclass(frozen=True)
class EtoroCandle:
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    complete: bool = True

    def validate(self, cutoff: datetime) -> "EtoroCandle":
        cutoff = _utc(cutoff)
        if self.timestamp > cutoff or not self.complete:
            raise EtoroDataError("future or incomplete candle is not admissible")
        values = (self.open, self.high, self.low, self.close, self.volume)
        if any(not value.is_finite() or value <= 0 for value in values[:4]):
            raise EtoroDataError("OHLC values must be finite and positive")
        if not self.volume.is_finite() or self.volume < 0:
            raise EtoroDataError("volume must be finite and nonnegative")
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close) or self.low > self.high:
            raise EtoroDataError("OHLC constraints are invalid")
        return self


CoverageStatus = Literal["PASS_5Y_DAILY", "INSUFFICIENT_DEPTH", "UNVERIFIED"]


@dataclass(frozen=True)
class CoverageReport:
    ticker: str
    status: CoverageStatus
    requested_limit: int
    candle_count: int
    earliest: datetime | None
    latest: datetime | None
    valid_trading_sessions: int
    gaps: tuple[date, ...]
    reason: str


class EtoroHistoricalDataClient:
    """Read-only historical candle client using an injected HTTP transport."""

    def __init__(
        self,
        transport: ReadOnlyMarketDataTransport,
        *,
        capability: MarketDataReadCapability,
        base_url: str = ETORO_BASE_URL,
        max_retries: int = 1,
    ) -> None:
        if base_url != ETORO_BASE_URL:
            raise ValueError("arbitrary eToro URLs are forbidden")
        if max_retries < 0 or max_retries > 2:
            raise ValueError("retry budget must be between zero and two")
        if capability.scope != "market-data-read":
            raise EtoroAccessBlocked("market-data-read capability is required")
        self._transport = transport
        self._max_retries = max_retries

    def resolve_instrument(self, ticker: str) -> EtoroInstrument:
        ticker = ticker.upper()
        if ticker not in APPROVED_TICKERS:
            raise EtoroDataError("ticker is outside the approved SideDeck universe")
        payload = self._get("/market-data/search", {"internalSymbolFull": ticker})
        rows = _rows(payload, keys=("items", "results", "data"))
        matches = [row for row in rows if row.get("internalSymbolFull") == ticker]
        if len(matches) != 1:
            raise EtoroDataError("instrument resolution is not deterministic")
        row = matches[0]
        try:
            raw_id = row.get("internalInstrumentId", row.get("instrumentId"))
            if raw_id is None or row.get("assetType") is None or row.get("currency") is None:
                raise EtoroDataError("instrument metadata is incomplete")
            instrument = EtoroInstrument(
                instrument_id=int(raw_id),
                ticker=ticker,
                asset_type=cast(Literal["EQUITY", "ETF"], str(row["assetType"]).upper()),
                venue=str(row.get("exchange", row.get("venue", ""))),
                currency=str(row["currency"]).upper(),
                leveraged=bool(row.get("leveraged", row.get("isLeveraged", False))),
                inverse=bool(row.get("inverse", row.get("isInverse", False))),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise EtoroDataError("instrument response is malformed") from exc
        return instrument.validate()

    def fetch_daily_candles(
        self, instrument: EtoroInstrument, *, limit: int = MAX_DAILY_CANDLES, cutoff: datetime
    ) -> tuple[EtoroCandle, ...]:
        instrument.validate()
        if limit <= 0:
            raise ValueError("candle limit must be positive")
        count = min(limit, MAX_DAILY_CANDLES)
        payload = self._get(
            f"/market-data/instruments/{instrument.instrument_id}/history/candles/desc/{DAILY_INTERVAL}/{count}",
            {},
        )
        candles: list[EtoroCandle] = []
        groups = _rows(payload, keys=("candles",))
        groups = [group for group in groups if _instrument_id(group) == instrument.instrument_id]
        if len(groups) != 1:
            raise EtoroDataError("candle response has no unique matching instrument group")
        rows = groups[0].get("candles")
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise EtoroDataError("candle instrument group is malformed")
        for row in rows:
            try:
                row_id = _instrument_id(row)
                if row_id is not None and row_id != instrument.instrument_id:
                    raise EtoroDataError("candle belongs to an unexpected instrument")
                candle = EtoroCandle(
                    timestamp=_parse_time(row.get("fromDate")),
                    open=_decimal(row["open"]), high=_decimal(row["high"]), low=_decimal(row["low"]),
                    close=_decimal(row["close"]), volume=_decimal(row.get("volume", 0)),
                    complete=bool(row.get("complete", row.get("isComplete", True))),
                )
                candle.validate(cutoff)
            except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
                raise EtoroDataError("candle response is malformed or not point-in-time safe") from exc
            candles.append(candle)
        ordered = tuple(sorted(candles, key=lambda value: value.timestamp))
        if len({candle.timestamp for candle in ordered}) != len(ordered):
            raise EtoroDataError("duplicate candle timestamps are not admissible")
        return ordered

    def scan_five_year_daily(
        self, instrument: EtoroInstrument, *, cutoff: datetime, candles: tuple[EtoroCandle, ...],
        exchange_sessions: frozenset[date] | None = None,
    ) -> CoverageReport:
        cutoff = _utc(cutoff)
        target = _five_years_before(cutoff.date())
        if not candles:
            return CoverageReport(instrument.ticker, "UNVERIFIED", MAX_DAILY_CANDLES, 0, None, None, 0, (), "no daily candles returned")
        valid = tuple(candle.validate(cutoff) for candle in candles)
        sessions = {candle.timestamp.date() for candle in valid}
        earliest, latest = valid[0].timestamp, valid[-1].timestamp
        if earliest.date() > target:
            status: CoverageStatus = "INSUFFICIENT_DEPTH"
            gaps: tuple[date, ...] = ()
            reason = "earliest available candle is newer than the five-year target date"
        elif exchange_sessions is None:
            status = "UNVERIFIED"
            gaps = ()
            reason = "five-year span might exist; verified exchange-session calendar is required"
        else:
            expected = frozenset(day for day in exchange_sessions if target <= day <= cutoff.date())
            gaps = tuple(sorted(expected - sessions))
            status = "PASS_5Y_DAILY" if len(expected) >= 1250 and earliest.date() <= target and not gaps and sessions >= expected else "INSUFFICIENT_DEPTH"
            reason = "complete explicit exchange-session coverage" if status == "PASS_5Y_DAILY" else "daily response does not establish complete five-year exchange-session coverage"
        return CoverageReport(instrument.ticker, status, MAX_DAILY_CANDLES, len(valid), earliest, latest, len(sessions), gaps, reason)

    def _get(self, path: str, params: Mapping[str, str]) -> Mapping[str, Any]:
        request_id = uuid4()
        for attempt in range(self._max_retries + 1):
            _validate_path(path)
            status, headers, body = self._transport.get(path, params, request_id)
            if len(body) > MAX_RESPONSE_BYTES:
                raise EtoroDataError("eToro response exceeds the bounded size limit")
            if status == 429 and attempt < self._max_retries:
                time.sleep(_bounded_retry_after(headers))
                continue
            if status in {401, 403}:
                raise EtoroAccessBlocked(f"eToro market-data access denied ({status})")
            if status < 200 or status >= 300:
                raise EtoroDataError(f"eToro market-data GET failed ({status})")
            try:
                parsed = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise EtoroDataError("eToro response was not valid JSON") from exc
            if not isinstance(parsed, dict):
                raise EtoroDataError("eToro response must be a JSON object")
            return parsed
        raise EtoroDataError("eToro market-data rate limit retry budget exhausted")


def _rows(payload: Mapping[str, Any], *, keys: tuple[str, ...]) -> list[Mapping[str, Any]]:
    data: Any = payload
    for key in keys:
        if isinstance(data, dict) and key in data:
            data = data[key]
            break
    if isinstance(data, dict):
        data = data.get("items", data.get("results", data.get("data", [])))
    if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
        raise EtoroDataError("eToro response has no tabular data")
    return data


def _instrument_id(row: Mapping[str, Any]) -> int | None:
    value = row.get("instrumentId", row.get("instrumentID"))
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _five_years_before(value: date) -> date:
    try:
        return value.replace(year=value.year - 5)
    except ValueError:
        return value.replace(year=value.year - 5, day=28)


def _validate_path(path: str) -> None:
    if path == "/market-data/search":
        return
    match = re.fullmatch(
        r"/market-data/instruments/([1-9][0-9]*)/history/candles/desc/OneDay/([1-9][0-9]*)",
        path,
    )
    if match and int(match.group(2)) <= MAX_DAILY_CANDLES:
        return
    raise EtoroDataError("GET path is outside the read-only market-data allowlist")


def _bounded_retry_after(headers: Mapping[str, str]) -> float:
    value = headers.get("Retry-After", "0")
    try:
        seconds = float(value)
    except ValueError:
        seconds = 0
    if seconds < 0 or seconds > 10:
        raise EtoroDataError("Retry-After exceeds the bounded retry policy")
    return seconds


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


def _parse_time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("candle timestamp is missing")
    return _utc(datetime.fromisoformat(value.replace("Z", "+00:00")))


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value))
