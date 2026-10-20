"""Strict offline parser of the documented eToro candle-history JSON.

No HTTP, broker access, or price-adjustment claims. Uncorroborated price evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sidedeck.application.p5_etoro_closing_price_evidence import _positive_price

INTERVALS = frozenset({"OneMinute", "FiveMinutes", "TenMinutes", "FifteenMinutes",
                       "ThirtyMinutes", "OneHour", "FourHours", "OneDay", "OneWeek"})


@dataclass(frozen=True)
class CandleEvidence:
    instrument_id: int
    interval: str
    from_date: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    validation: str = "BROKER_REPORTED_UNCORROBORATED"


def parse_candle_history(payload: object, *, instrument_id: int,
                         interval: str, max_count: int = 1000) -> list[CandleEvidence]:
    if isinstance(instrument_id, bool) or not isinstance(instrument_id, int) or instrument_id <= 0:
        raise ValueError("invalid instrument")
    if interval not in INTERVALS or not 1 <= max_count <= 1000:
        raise ValueError("unsupported candle request")
    if not isinstance(payload, dict) or payload.get("interval") != interval:
        raise ValueError("candle interval mismatch")
    groups: Any = payload.get("candles")
    if not isinstance(groups, list) or len(groups) != 1:
        raise ValueError("expected exactly one instrument group")
    group = groups[0]
    if not isinstance(group, dict) or group.get("instrumentId") != instrument_id:
        raise ValueError("candle instrument mismatch")
    bars: Any = group.get("candles")
    if not isinstance(bars, list) or not bars or len(bars) > max_count:
        raise ValueError("invalid candle count")
    output: list[CandleEvidence] = []
    seen: set[datetime] = set()
    for bar in bars:
        if not isinstance(bar, dict) or bar.get("instrumentID") != instrument_id:
            raise ValueError("candle identity mismatch")
        raw_date = bar.get("fromDate")
        if not isinstance(raw_date, str):
            raise ValueError("invalid candle date")
        try:
            date = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("invalid candle date") from exc
        if date.utcoffset() is None or date in seen:
            raise ValueError("naive or repeated candle time")
        seen.add(date)
        prices = [_positive_price(bar.get(key)) for key in ("open", "high", "low", "close")]
        open_price, high_price, low_price, close_price = prices
        if (low_price > min(open_price, close_price)
                or high_price < max(open_price, close_price)
                or low_price > high_price):
            raise ValueError("inconsistent candle OHLC")
        volume = bar.get("volume")
        if isinstance(volume, bool) or not isinstance(volume, (int, float, str, Decimal)):
            raise ValueError("invalid candle volume")
        try:
            v = Decimal(str(volume))
        except Exception as exc:
            raise ValueError("invalid candle volume") from exc
        if not v.is_finite() or v < 0:
            raise ValueError("negative or invalid candle volume")
        output.append(CandleEvidence(
            instrument_id, interval, date, open_price, high_price, low_price, close_price, v,
        ))
    if any(a.from_date >= b.from_date for a, b in zip(output, output[1:])):
        raise ValueError("candles must be strictly chronological")
    return output
