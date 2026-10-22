"""Deterministic, provenance-tagged regular US equity session calendar.

This calendar contains the bounded 2021-2026 SD-021 daily-session window.
Weekdays are never silently treated as sessions; closure dates are explicit.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


NASDAQ_TRADER_2026 = "https://nasdaqtrader.com/Trader.aspx?id=Calendar"
NASDAQ_TRADER_2021_2026 = NASDAQ_TRADER_2026 + "#2021-2026"
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
US_EQUITY_CLOSED_2021_2025: dict[date, str] = {
    date(2021, 11, 25): "Thanksgiving Day",
    date(2021, 12, 24): "Christmas Holiday (Observed)",
    date(2022, 1, 17): "Martin Luther King, Jr. Day",
    date(2022, 2, 21): "Presidents' Day",
    date(2022, 4, 15): "Good Friday",
    date(2022, 5, 30): "Memorial Day",
    date(2022, 6, 20): "Juneteenth (Observed)",
    date(2022, 7, 4): "Independence Day",
    date(2022, 9, 5): "Labor Day",
    date(2022, 11, 24): "Thanksgiving Day",
    date(2022, 12, 26): "Christmas Holiday (Observed)",
    date(2023, 1, 2): "New Year's Day (Observed)",
    date(2023, 1, 16): "Martin Luther King, Jr. Day",
    date(2023, 2, 20): "Presidents' Day",
    date(2023, 4, 7): "Good Friday",
    date(2023, 5, 29): "Memorial Day",
    date(2023, 6, 19): "Juneteenth",
    date(2023, 7, 4): "Independence Day",
    date(2023, 9, 4): "Labor Day",
    date(2023, 11, 23): "Thanksgiving Day",
    date(2023, 12, 25): "Christmas Day",
    date(2024, 1, 1): "New Year's Day",
    date(2024, 1, 15): "Martin Luther King, Jr. Day",
    date(2024, 2, 19): "Presidents' Day",
    date(2024, 3, 29): "Good Friday",
    date(2024, 5, 27): "Memorial Day",
    date(2024, 6, 19): "Juneteenth",
    date(2024, 7, 4): "Independence Day",
    date(2024, 9, 2): "Labor Day",
    date(2024, 11, 28): "Thanksgiving Day",
    date(2024, 12, 25): "Christmas Day",
    date(2025, 1, 1): "New Year's Day",
    date(2025, 1, 9): "National Day of Mourning",
    date(2025, 1, 20): "Martin Luther King, Jr. Day",
    date(2025, 2, 17): "Presidents' Day",
    date(2025, 4, 18): "Good Friday",
    date(2025, 5, 26): "Memorial Day",
    date(2025, 6, 19): "Juneteenth",
    date(2025, 7, 4): "Independence Day",
    date(2025, 9, 1): "Labor Day",
    date(2025, 11, 27): "Thanksgiving Day",
    date(2025, 12, 25): "Christmas Day",
}
US_EQUITY_CLOSED = {**US_EQUITY_CLOSED_2021_2025, **US_EQUITY_CLOSED_2026}


@dataclass(frozen=True)
class SessionCoverage:
    expected: tuple[date, ...]
    observed: tuple[date, ...]
    missing: tuple[date, ...]
    unexpected: tuple[date, ...]
    status: str
    calendar_source: str = NASDAQ_TRADER_2021_2026


def is_regular_session(day: date) -> bool:
    return day.weekday() < 5 and day not in US_EQUITY_CLOSED


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


# Years whose full-closure list above is complete. 2021 holds only two late-year dates,
# so sessions in 2021 must not be inferred from this table.
COMPLETE_CALENDAR_YEARS: frozenset[int] = frozenset(range(2022, 2027))
