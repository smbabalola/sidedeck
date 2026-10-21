"""Offline parser for an owner-supplied Yahoo historical CSV.

No Yahoo transport is included. The parser uses the historical ``Close``
column, never ``Adj Close``, and retains provenance as unverified until the
owner supplies a lawful export with source and adjustment evidence.
"""
from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal, InvalidOperation
from io import StringIO
from typing import Any

from sidedeck.application.us_equity_calendar import is_regular_session


class YahooHistoryUnavailable(ValueError):
    pass


def parse_yahoo_csv(text: str, *, ticker: str, source_url: str, cutoff: date) -> dict[str, Any]:
    if ticker != "MSFT" or not source_url:
        raise YahooHistoryUnavailable("exact MSFT identity and source URL are required")
    reader = csv.DictReader(StringIO(text))
    if not reader.fieldnames or "Date" not in reader.fieldnames or "Close" not in reader.fieldnames:
        raise YahooHistoryUnavailable("Yahoo CSV must contain Date and Close columns")
    records: list[dict[str, str]] = []
    seen: set[date] = set()
    for row in reader:
        try:
            day = date.fromisoformat(str(row["Date"]))
            close = Decimal(str(row["Close"]))
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            raise YahooHistoryUnavailable("invalid Yahoo date or Close") from exc
        if day > cutoff or day in seen or not close.is_finite() or close <= 0:
            raise YahooHistoryUnavailable("future, duplicate or invalid Yahoo Close")
        if not is_regular_session(day):
            raise YahooHistoryUnavailable("date is not a regular trading session")
        seen.add(day)
        records.append({"date": day.isoformat(), "close": str(close), "source_id": "yahoo:MSFT:Close"})
    if not records:
        raise YahooHistoryUnavailable("Yahoo historical rows are unavailable")
    records.sort(key=lambda row: row["date"])
    return {
        "ticker": ticker, "instrument_id": "US:MSFT", "exchange": "NASDAQ",
        "currency": "USD", "session": "REGULAR", "adjustment": "unknown",
        "source": "yahoo:historical", "source_identity": "yahoo_owner_supplied",
        "records": records, "adj_close_present": "Adj Close" in reader.fieldnames,
        "provenance_verified": False, "historical_price_validation": "PENDING",
        "source_url": source_url, "research_only": True, "broker_execution": "DISABLED",
    }
