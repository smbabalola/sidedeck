"""Offline-only parsing of eToro documented closing-price response.

There is intentionally no HTTP client or credential handling in this module.
A broker's 'officialClosingPrice' label does not establish a SIP-verified close.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any


@dataclass(frozen=True)
class ClosingPriceObservation:
    instrument_id: int
    interval: str
    date: datetime
    price: Decimal
    validation: str = "BROKER_REPORTED_UNCORROBORATED"


def _positive_price(raw: object) -> Decimal:
    if isinstance(raw, bool) or not isinstance(raw, (float, int, str, Decimal)):
        raise ValueError("invalid closing price type")
    try:
        result = Decimal(str(raw))
    except InvalidOperation as exc:
        raise ValueError("invalid closing price") from exc
    if not result.is_finite() or result <= 0:
        raise ValueError("nonpositive closing price")
    return result


def parse_closing_prices(payload: object, *, instrument_id: int) -> list[ClosingPriceObservation]:
    """Parse documented daily/weekly/monthly entries, reject sentinels and duplicates.

    Does NOT certify adjustment basis, SIP consolidation or completeness.
    """
    if not isinstance(instrument_id, int) or isinstance(instrument_id, bool) or instrument_id <= 0:
        raise ValueError("invalid requested instrument")
    if not isinstance(payload, list):
        raise ValueError("expected list of instruments")
    matches = [x for x in payload if isinstance(x, dict) and x.get("instrumentId") == instrument_id]
    if len(matches) != 1:
        raise ValueError("missing or duplicate exact instrument")
    item = matches[0]
    if not isinstance(item.get("closingPrices"), dict):
        raise ValueError("missing closing prices")
    observations: list[ClosingPriceObservation] = []
    for interval in ("daily", "weekly", "monthly"):
        value: Any = item["closingPrices"].get(interval)
        if value is None:
            continue
        if not isinstance(value, dict) or not isinstance(value.get("date"), str):
            raise ValueError("malformed interval")
        date_str = value["date"]
        if date_str.startswith("0001-") and value.get("price") == -1:
            continue  # documented unavailable marker, never a tradeable observation
        try:
            date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("invalid timestamp") from exc
        if date.tzinfo is None or date.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        observations.append(ClosingPriceObservation(
            instrument_id=instrument_id, interval=interval, date=date,
            price=_positive_price(value.get("price")),
        ))
    if not observations:
        raise ValueError("no usable closing price")
    return observations
