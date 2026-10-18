"""Offline, licence-gated validation of Tiingo-shaped end-of-day equity history.

No network transport, API credentials, trading or broker calls are present.
The source can contain retrospectively adjusted prices; validation does not
establish point-in-time market knowledge or permission to redistribute.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from typing import Any, Literal, Mapping, cast

from .instruments import get_instrument

APPROVED_EOD_SYMBOLS = frozenset({"AAPL", "MSFT", "SPY", "QQQ"})
NUMERIC_FIELDS = (
    "open", "high", "low", "close", "volume",
    "adjOpen", "adjHigh", "adjLow", "adjClose", "adjVolume",
    "divCash", "splitFactor",
)


class HistoricalDataError(ValueError):
    """An EOD record is unsupported, unlicensed or internally inconsistent."""


@dataclass(frozen=True)
class EodBar:
    day: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    adj_open: Decimal
    adj_high: Decimal
    adj_low: Decimal
    adj_close: Decimal
    adj_volume: Decimal
    dividend: Decimal
    split_factor: Decimal


@dataclass(frozen=True)
class HistoricalEodDataset:
    ticker: str
    collected_at_utc: datetime
    source: Literal["tiingo-eod"]
    payload_sha256: str
    bars: tuple[EodBar, ...]
    point_in_time_verified: bool = False

    @property
    def earliest(self) -> date:
        return self.bars[0].day

    @property
    def latest(self) -> date:
        return self.bars[-1].day


@dataclass(frozen=True)
class DailyCoverage:
    ticker: str
    status: Literal["INSUFFICIENT_DEPTH", "UNVERIFIED", "PASS_5Y_DAILY"]
    first_date: date
    last_date: date
    observed_sessions: int
    missing_sessions: tuple[date, ...]
    point_in_time_verified: bool = False


def _number(record: Mapping[str, Any], name: str) -> Decimal:
    try:
        value = record[name]
        if isinstance(value, bool) or value is None:
            raise ValueError("missing numeric field")
        result = Decimal(str(value))
    except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
        raise HistoricalDataError(f"invalid EOD numeric field: {name}") from exc
    if not result.is_finite():
        raise HistoricalDataError(f"non-finite EOD field: {name}")
    return result


def _day(value: object) -> date:
    if not isinstance(value, str):
        raise HistoricalDataError("EOD date must be a string")
    try:
        if len(value) == 10:
            return date.fromisoformat(value)
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None or dt.utcoffset() is None:
            raise HistoricalDataError("timestamp requires timezone")
        return dt.astimezone(timezone.utc).date()
    except (ValueError, OverflowError) as exc:
        raise HistoricalDataError("malformed EOD date") from exc


def _check_ohlc(
    price_open: Decimal, price_high: Decimal, price_low: Decimal,
    price_close: Decimal, prefix: str,
) -> None:
    if (
        min(price_open, price_high, price_low, price_close) <= 0
        or price_high < max(price_open, price_close)
        or price_low > min(price_open, price_close)
        or price_low > price_high
    ):
        raise HistoricalDataError(f"invalid {prefix} OHLC prices")


def parse_tiingo_eod(
    payload: object, *, ticker: str, collected_at: datetime, license_confirmed: bool
) -> HistoricalEodDataset:
    """Parse an already-acquired private EOD response; **never** fetch it."""
    if not license_confirmed:
        raise HistoricalDataError("data licence must be confirmed before import")
    symbol = ticker.upper()
    if symbol not in APPROVED_EOD_SYMBOLS:
        raise HistoricalDataError("unapproved ticker")
    get_instrument(symbol)
    if collected_at.tzinfo is None or collected_at.utcoffset() is None:
        raise HistoricalDataError("collection timestamp must be timezone-aware")
    seen: set[date] = set()
    bars: list[EodBar] = []
    if not isinstance(payload, list) or not payload:
        raise HistoricalDataError("expected nonempty Tiingo EOD JSON array")
    try:
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest()
    except (TypeError, ValueError) as exc:
        raise HistoricalDataError("non-serializable EOD response") from exc
    for raw in payload:
        if not isinstance(raw, dict):
            raise HistoricalDataError("EOD row must be a JSON object")
        row = cast(Mapping[str, Any], raw)
        day = _day(row.get("date"))
        if day in seen:
            raise HistoricalDataError("duplicate EOD trading date")
        if day > collected_at.astimezone(timezone.utc).date():
            raise HistoricalDataError("future EOD observation")
        nums = {name: _number(row, name) for name in NUMERIC_FIELDS}
        _check_ohlc(nums["open"], nums["high"], nums["low"], nums["close"], "raw")
        _check_ohlc(nums["adjOpen"], nums["adjHigh"], nums["adjLow"], nums["adjClose"], "adjusted")
        if (nums["volume"] < 0 or nums["adjVolume"] < 0 or
                nums["divCash"] < 0 or nums["splitFactor"] <= 0):
            raise HistoricalDataError("invalid volume, dividend or split")
        bars.append(EodBar(
            day=day, open=nums["open"], high=nums["high"], low=nums["low"],
            close=nums["close"], volume=nums["volume"],
            adj_open=nums["adjOpen"], adj_high=nums["adjHigh"],
            adj_low=nums["adjLow"], adj_close=nums["adjClose"],
            adj_volume=nums["adjVolume"], dividend=nums["divCash"],
            split_factor=nums["splitFactor"],
        ))
        seen.add(day)
    bars.sort(key=lambda bar: bar.day)
    return HistoricalEodDataset(
        ticker=symbol, collected_at_utc=collected_at.astimezone(timezone.utc),
        source="tiingo-eod", payload_sha256=digest, bars=tuple(bars),
    )


def _five_years_before(value: date) -> date:
    try:
        return value.replace(year=value.year - 5)
    except ValueError:
        return value.replace(year=value.year - 5, day=28)


def assess_daily_coverage(
    dataset: HistoricalEodDataset, *, through: date,
    verified_sessions: frozenset[date] | None = None,
) -> DailyCoverage:
    """Check dates only; this cannot establish adjustment-vintage PIT validity."""
    target = _five_years_before(through)
    if dataset.earliest > target or dataset.latest < through - timedelta(days=7):
        status: Literal["INSUFFICIENT_DEPTH", "UNVERIFIED", "PASS_5Y_DAILY"] = "INSUFFICIENT_DEPTH"
        missing: tuple[date, ...] = ()
    elif verified_sessions is None:
        status = "UNVERIFIED"
        missing = ()
    else:
        expected = frozenset(day for day in verified_sessions if target <= day <= through)
        observed = {bar.day for bar in dataset.bars}
        missing = tuple(sorted(expected - observed))
        if (len(expected) >= 1200 and expected and
                min(expected) <= target + timedelta(days=7) and
                max(expected) >= through - timedelta(days=7) and
                not missing):
            status = "PASS_5Y_DAILY"
        else:
            status = "INSUFFICIENT_DEPTH"
    return DailyCoverage(
        ticker=dataset.ticker, status=status,
        first_date=dataset.earliest, last_date=dataset.latest,
        observed_sessions=len(dataset.bars), missing_sessions=missing,
    )
