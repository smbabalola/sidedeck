"""Offline parser for independently supplied Nasdaq historical-price evidence.

This module has no Nasdaq transport and does not imply that public Nasdaq pages
or Data Link access is free, complete, adjusted, or currently entitled.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any


class NasdaqDataUnavailable(ValueError):
    pass


def parse_nasdaq_daily(payload: dict[str, Any], *, ticker: str, cutoff: date) -> dict[str, Any]:
    if ticker != "MSFT" or payload.get("symbol") != ticker:
        raise NasdaqDataUnavailable("exact MSFT identity is required")
    if payload.get("currency") != "USD" or payload.get("session") != "REGULAR":
        raise NasdaqDataUnavailable("USD regular-session evidence is required")
    adjustment = payload.get("adjustment")
    if adjustment not in ("raw_close", "split_adjusted_close"):
        raise NasdaqDataUnavailable("explicit price adjustment basis is required")
    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows:
        raise NasdaqDataUnavailable("Nasdaq daily rows are unavailable")
    records: list[dict[str, str]] = []
    seen: set[date] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise NasdaqDataUnavailable("invalid Nasdaq row")
        try:
            day = date.fromisoformat(str(row["date"]))
            close = Decimal(str(row["close"]))
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            raise NasdaqDataUnavailable("invalid Nasdaq date or close") from exc
        if day > cutoff or day in seen or not close.is_finite() or close <= 0:
            raise NasdaqDataUnavailable("future, duplicate or invalid Nasdaq close")
        if day.weekday() >= 5:
            raise NasdaqDataUnavailable("weekend is not a trading session")
        seen.add(day)
        records.append({"date": day.isoformat(), "close": str(close),
                        "source_id": str(row.get("source_id", ""))})
    if any(not record["source_id"] for record in records):
        raise NasdaqDataUnavailable("Nasdaq source identity is missing")
    records.sort(key=lambda row: row["date"])
    return {"ticker": ticker, "instrument_id": "US:MSFT", "exchange": "NASDAQ",
            "currency": "USD", "session": "REGULAR", "adjustment": adjustment,
            "source": "nasdaq:historical", "source_identity": "nasdaq_supplied",
            "records": records, "provenance_verified": False,
            "historical_price_validation": "PENDING", "research_only": True,
            "broker_execution": "DISABLED"}
