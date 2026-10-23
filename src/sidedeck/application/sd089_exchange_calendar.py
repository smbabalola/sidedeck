"""SD-089 multi-exchange trading calendars (offline, deterministic).

Each exchange keeps its own time zone, regular hours, closures and half days, so a
US session is never assumed to share hours or holidays with London. Sessions are
computed in the exchange's local zone and converted to UTC; daylight-saving
changes therefore move the UTC times, never the local session.

Covered years are explicit. A date outside them raises ``CalendarError`` rather
than guessing that a weekday is a session.

Calendars:

``XNYS``  NYSE/Nasdaq regular session 09:30-16:00 America/New_York, 13:00 early
          closes. Closures come from :mod:`us_equity_calendar` (Nasdaq Trader).
``XLON``  London Stock Exchange continuous trading 08:00-16:30 Europe/London
          (opening auction 07:50, closing auction 16:30-16:35 are not part of the
          continuous session). Half days close continuous trading at 12:30.
          Closures are England & Wales bank holidays plus exceptional closures.

Source status for XLON is ``TRANSCRIBED_RULE_CROSSCHECKED``: the table below was
transcribed and is checked in tests against an independent rule-based derivation
(Easter computus plus the statutory England & Wales bank-holiday rules). It has
**not** yet been corroborated against gov.uk/bank-holidays.json or an LSE business
days notice (bounded request in SD-094). G1 data acceptance must not treat it as
authoritative until that corroboration is recorded.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Mapping
from zoneinfo import ZoneInfo

from sidedeck.application.us_equity_calendar import (
    COMPLETE_CALENDAR_YEARS as US_COMPLETE_YEARS,
)
from sidedeck.application.us_equity_calendar import (
    NASDAQ_TRADER_2021_2026,
    US_EQUITY_CLOSED,
)


class CalendarError(ValueError):
    pass


@dataclass(frozen=True)
class ExchangeSession:
    calendar_id: str
    day: date
    open_utc: datetime
    close_utc: datetime
    early_close: bool


@dataclass(frozen=True)
class ExchangeCalendar:
    calendar_id: str
    name: str
    timezone: str
    regular_open: time
    regular_close: time
    early_close_time: time
    covered_years: frozenset[int]
    closures: Mapping[date, str]
    early_closes: Mapping[date, str]
    source_status: str
    source_note: str
    zone: ZoneInfo = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "zone", ZoneInfo(self.timezone))
        if not self.regular_open < self.early_close_time < self.regular_close:
            raise CalendarError(f"{self.calendar_id}: inconsistent session hours")
        overlap = set(self.closures) & set(self.early_closes)
        if overlap:
            raise CalendarError(f"{self.calendar_id}: dates both closed and half day: {overlap}")
        for day in (*self.closures, *self.early_closes):
            if day.weekday() >= 5:
                raise CalendarError(f"{self.calendar_id}: weekend date {day} listed")
            if day.year not in self.covered_years:
                raise CalendarError(f"{self.calendar_id}: {day} outside covered years")

    # --- day level -----------------------------------------------------------------
    def _check(self, day: date) -> None:
        if day.year not in self.covered_years:
            raise CalendarError(
                f"{self.calendar_id} calendar does not cover {day.year}; refusing to guess"
            )

    def is_session(self, day: date) -> bool:
        self._check(day)
        return day.weekday() < 5 and day not in self.closures

    def session(self, day: date) -> ExchangeSession | None:
        if not self.is_session(day):
            return None
        early = day in self.early_closes
        open_local = datetime.combine(day, self.regular_open, self.zone)
        close_local = datetime.combine(
            day, self.early_close_time if early else self.regular_close, self.zone
        )
        return ExchangeSession(
            self.calendar_id, day, open_local.astimezone(UTC), close_local.astimezone(UTC), early
        )

    def sessions_between(self, start: date, end: date) -> tuple[date, ...]:
        if end < start:
            raise CalendarError("calendar end must not precede start")
        days: list[date] = []
        current = start
        while current <= end:
            if self.is_session(current):
                days.append(current)
            current += timedelta(days=1)
        return tuple(days)

    def previous_session(self, day: date) -> date:
        current = day - timedelta(days=1)
        while not self.is_session(current):
            current -= timedelta(days=1)
        return current

    def next_session(self, day: date) -> date:
        current = day + timedelta(days=1)
        while not self.is_session(current):
            current += timedelta(days=1)
        return current

    # --- instant level ---------------------------------------------------------------
    def local_date(self, at: datetime) -> date:
        if at.tzinfo is None:
            raise CalendarError("timezone-aware time required")
        return at.astimezone(self.zone).date()

    def is_open(self, at: datetime) -> bool:
        """True only inside continuous trading (open inclusive, close exclusive)."""
        session = self.session(self.local_date(at))
        if session is None:
            return False
        moment = at.astimezone(UTC)
        return session.open_utc <= moment < session.close_utc

    def last_completed_session(self, at: datetime) -> date:
        """Latest session whose close is at or before ``at`` (the newest valid daily cutoff)."""
        day = self.local_date(at)
        session = self.session(day)
        if session is not None and session.close_utc <= at.astimezone(UTC):
            return day
        return self.previous_session(day)


# --- XNYS ------------------------------------------------------------------------------

US_EARLY_CLOSES: dict[date, str] = {
    date(2022, 11, 25): "Day after Thanksgiving",
    date(2023, 7, 3): "Independence Day eve", date(2023, 11, 24): "Day after Thanksgiving",
    date(2024, 7, 3): "Independence Day eve", date(2024, 11, 29): "Day after Thanksgiving",
    date(2024, 12, 24): "Christmas Eve",
    date(2025, 7, 3): "Independence Day eve", date(2025, 11, 28): "Day after Thanksgiving",
    date(2025, 12, 24): "Christmas Eve",
    date(2026, 11, 27): "Day after Thanksgiving", date(2026, 12, 24): "Christmas Eve",
}

XNYS = ExchangeCalendar(
    calendar_id="XNYS", name="NYSE / Nasdaq regular session", timezone="America/New_York",
    regular_open=time(9, 30), regular_close=time(16, 0), early_close_time=time(13, 0),
    covered_years=US_COMPLETE_YEARS,
    closures={d: n for d, n in US_EQUITY_CLOSED.items() if d.year in US_COMPLETE_YEARS},
    early_closes=US_EARLY_CLOSES,
    source_status="TRANSCRIBED_EXCHANGE_PUBLISHED",
    source_note=f"closures: {NASDAQ_TRADER_2021_2026}; 2026 early closes cross-read from nyse.com",
)


# --- XLON ------------------------------------------------------------------------------

UK_CLOSURES: dict[date, str] = {
    # 2022
    date(2022, 1, 3): "New Year's Day (substitute)",
    date(2022, 4, 15): "Good Friday", date(2022, 4, 18): "Easter Monday",
    date(2022, 5, 2): "Early May bank holiday",
    date(2022, 6, 2): "Spring bank holiday (moved)",
    date(2022, 6, 3): "Platinum Jubilee bank holiday (exceptional)",
    date(2022, 8, 29): "Summer bank holiday",
    date(2022, 9, 19): "State Funeral of Queen Elizabeth II (exceptional)",
    date(2022, 12, 26): "Boxing Day", date(2022, 12, 27): "Christmas Day (substitute)",
    # 2023
    date(2023, 1, 2): "New Year's Day (substitute)",
    date(2023, 4, 7): "Good Friday", date(2023, 4, 10): "Easter Monday",
    date(2023, 5, 1): "Early May bank holiday",
    date(2023, 5, 8): "Coronation of King Charles III bank holiday (exceptional)",
    date(2023, 5, 29): "Spring bank holiday", date(2023, 8, 28): "Summer bank holiday",
    date(2023, 12, 25): "Christmas Day", date(2023, 12, 26): "Boxing Day",
    # 2024
    date(2024, 1, 1): "New Year's Day",
    date(2024, 3, 29): "Good Friday", date(2024, 4, 1): "Easter Monday",
    date(2024, 5, 6): "Early May bank holiday", date(2024, 5, 27): "Spring bank holiday",
    date(2024, 8, 26): "Summer bank holiday",
    date(2024, 12, 25): "Christmas Day", date(2024, 12, 26): "Boxing Day",
    # 2025
    date(2025, 1, 1): "New Year's Day",
    date(2025, 4, 18): "Good Friday", date(2025, 4, 21): "Easter Monday",
    date(2025, 5, 5): "Early May bank holiday", date(2025, 5, 26): "Spring bank holiday",
    date(2025, 8, 25): "Summer bank holiday",
    date(2025, 12, 25): "Christmas Day", date(2025, 12, 26): "Boxing Day",
    # 2026
    date(2026, 1, 1): "New Year's Day",
    date(2026, 4, 3): "Good Friday", date(2026, 4, 6): "Easter Monday",
    date(2026, 5, 4): "Early May bank holiday", date(2026, 5, 25): "Spring bank holiday",
    date(2026, 8, 31): "Summer bank holiday",
    date(2026, 12, 25): "Christmas Day", date(2026, 12, 28): "Boxing Day (substitute)",
    # 2027
    date(2027, 1, 1): "New Year's Day",
    date(2027, 3, 26): "Good Friday", date(2027, 3, 29): "Easter Monday",
    date(2027, 5, 3): "Early May bank holiday", date(2027, 5, 31): "Spring bank holiday",
    date(2027, 8, 30): "Summer bank holiday",
    date(2027, 12, 27): "Christmas Day (substitute)",
    date(2027, 12, 28): "Boxing Day (substitute)",
}
# Exceptional one-off closures and moved holidays (not derivable from statutory rules).
UK_EXCEPTIONAL_CLOSURES: frozenset[date] = frozenset({
    date(2022, 6, 2), date(2022, 6, 3), date(2022, 9, 19), date(2023, 5, 8),
})
# The statutory late-May Monday that was moved away in 2022 (to 2 June).
UK_MOVED_AWAY: frozenset[date] = frozenset({date(2022, 5, 30)})
# LSE half days: last business day before Christmas and before New Year.
UK_HALF_DAYS: dict[date, str] = {
    date(2022, 12, 23): "Christmas Eve half day (24th on Saturday)",
    date(2022, 12, 30): "New Year's Eve half day (31st on Saturday)",
    date(2023, 12, 22): "Christmas Eve half day (24th on Sunday)",
    date(2023, 12, 29): "New Year's Eve half day (31st on Sunday)",
    date(2024, 12, 24): "Christmas Eve half day", date(2024, 12, 31): "New Year's Eve half day",
    date(2025, 12, 24): "Christmas Eve half day", date(2025, 12, 31): "New Year's Eve half day",
    date(2026, 12, 24): "Christmas Eve half day", date(2026, 12, 31): "New Year's Eve half day",
    date(2027, 12, 24): "Christmas Eve half day", date(2027, 12, 31): "New Year's Eve half day",
}
UK_COVERED_YEARS: frozenset[int] = frozenset(range(2022, 2028))
# Half days inferred only from the 'last weekday before a weekend 24th/31st' rule; the
# independent derivation uses the same rule, so it cannot corroborate them. They need an
# LSE business-days notice before G1 (independent review L3). Until then they are listed.
UK_UNCORROBORATED_HALF_DAYS: frozenset[date] = frozenset({
    date(2022, 12, 23), date(2022, 12, 30), date(2023, 12, 22), date(2023, 12, 29),
})

XLON = ExchangeCalendar(
    calendar_id="XLON", name="London Stock Exchange continuous trading",
    timezone="Europe/London",
    regular_open=time(8, 0), regular_close=time(16, 30), early_close_time=time(12, 30),
    covered_years=UK_COVERED_YEARS, closures=UK_CLOSURES, early_closes=UK_HALF_DAYS,
    source_status="TRANSCRIBED_RULE_CROSSCHECKED",
    source_note=(
        "England & Wales bank holidays and LSE half days transcribed; cross-checked against "
        "rule-based derivation in tests; authoritative corroboration (gov.uk bank-holidays.json, "
        "LSE business days notice) pending SD-094"
    ),
)

CALENDARS: dict[str, ExchangeCalendar] = {"XNYS": XNYS, "XLON": XLON}
# SD-065 exchange identifiers -> trading calendar.
EXCHANGE_CALENDAR: dict[str, str] = {
    "NYSE": "XNYS", "NASDAQ": "XNYS", "NYSE_ARCA": "XNYS", "NYSE_AMERICAN": "XNYS",
    "CBOE_BZX": "XNYS", "LSE": "XLON",
}


def calendar(calendar_id: str) -> ExchangeCalendar:
    try:
        return CALENDARS[calendar_id]
    except KeyError as exc:
        raise CalendarError(f"unknown calendar {calendar_id!r}") from exc


def calendar_for_exchange(exchange: str) -> ExchangeCalendar:
    try:
        return CALENDARS[EXCHANGE_CALENDAR[exchange]]
    except KeyError as exc:
        raise CalendarError(f"no trading calendar for exchange {exchange!r}") from exc


# --- independent rule-based derivation (used only to cross-check the table) ------------

def easter_sunday(year: int) -> date:
    """Anonymous Gregorian computus (Meeus/Jones/Butcher)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7  # noqa: E741 - standard algorithm name
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = (h + l - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def _first_monday(year: int, month: int) -> date:
    d = date(year, month, 1)
    return d + timedelta(days=(7 - d.weekday()) % 7)


def _last_monday(year: int, month: int) -> date:
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    d = nxt - timedelta(days=1)
    return d - timedelta(days=d.weekday())


def derived_england_wales_bank_holidays(year: int) -> set[date]:
    """Statutory pattern only; exceptional/moved holidays are not derivable here."""
    easter = easter_sunday(year)
    days = {
        easter - timedelta(days=2), easter + timedelta(days=1),
        _first_monday(year, 5), _last_monday(year, 5), _last_monday(year, 8),
    }
    new_year = date(year, 1, 1)
    days.add(new_year + timedelta(days={5: 2, 6: 1}.get(new_year.weekday(), 0)))
    christmas = date(year, 12, 25)
    if christmas.weekday() == 5:      # Sat: substitutes Mon 27 and Tue 28
        days |= {date(year, 12, 27), date(year, 12, 28)}
    elif christmas.weekday() == 6:    # Sun: Boxing Day Mon 26, Christmas substitute Tue 27
        days |= {date(year, 12, 26), date(year, 12, 27)}
    elif christmas.weekday() == 4:    # Fri: Boxing Day (Sat) substitute Mon 28
        days |= {christmas, date(year, 12, 28)}
    else:
        days |= {christmas, date(year, 12, 26)}
    return days


def derived_lse_half_days(year: int) -> set[date]:
    out: set[date] = set()
    for anchor in (date(year, 12, 24), date(year, 12, 31)):
        d = anchor
        while d.weekday() >= 5:
            d -= timedelta(days=1)
        out.add(d)
    return out
