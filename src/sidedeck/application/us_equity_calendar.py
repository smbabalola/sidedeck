"""Deterministic, provenance-tagged regular US equity session calendar.

This is intentionally a small offline calendar for the 2026 SD-004 window.
It must be extended from an official exchange schedule before being used for
another year; weekdays are never silently treated as sessions.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


NASDAQ_TRADER_2026 = "https://nasdaqtrader.com/Trader.aspx?id=Calendar"
US_EQUITY_CLOSED_2026: dict[date, str] = {
    date(2026, 1, 1): "New Year's Day (Observed)",
    date(2026, 1, 19): "Martin Luther King, Jr. Day",
    date(2026, 2, 16): "Presidents' Day",
    date(2026, 4, 3): "Good Friday",
    date(2026, 5, 25): "Memorial Day",
    date(2026, 6, 19): "Juneteenth (Observed)",
    date(2026, 7, 3): "Independence Day (Observed)",
    date(2026, 9, 7): "Labor Day",
    date(2026, 11, 26): "Thanksgiving Day",
    date(2026, 12, 25): "Christmas Holiday",
}


@dataclass(frozen=True)
class SessionCoverage:
    expected: tuple[date, ...]
    observed: tuple[date, ...]
    missing: tuple[date, ...]
    unexpected: tuple[date, ...]
    status: str
    calendar_source: str = NASDAQ_TRADER_2026


def is_regular_session(day: date) -> bool:
    return day.weekday() < 5 and day not in US_EQUITY_CLOSED_2026


def expected_regular_sessions(start: date, end: date) -> tuple[date, ...]:
    if end < start:
        raise ValueError("calendar end must not precede start")
    days: list[date] = []
    current = start
    while current <= end:
        if is_regular_session(current):
            days.append(current)
        current += timedelta(days=1)
    return tuple(days)


def validate_session_coverage(
    observed: list[date] | tuple[date, ...], *, start: date, end: date
) -> SessionCoverage:
    expected = expected_regular_sessions(start, end)
    observed_unique = tuple(sorted(set(observed)))
    expected_set = set(expected)
    observed_set = set(observed_unique)
    missing = tuple(day for day in expected if day not in observed_set)
    unexpected = tuple(day for day in observed_unique if day not in expected_set)
    status = "VALIDATED" if not missing and not unexpected and len(observed) == len(observed_unique) else "REJECTED"
    return SessionCoverage(expected, observed_unique, missing, unexpected, status)
