from __future__ import annotations

from datetime import UTC, date, datetime, time

import pytest

from sidedeck.application.sd089_exchange_calendar import (
    UK_CLOSURES,
    UK_COVERED_YEARS,
    UK_EXCEPTIONAL_CLOSURES,
    UK_HALF_DAYS,
    UK_MOVED_AWAY,
    XLON,
    XNYS,
    CalendarError,
    ExchangeCalendar,
    calendar_for_exchange,
    derived_england_wales_bank_holidays,
    derived_lse_half_days,
    easter_sunday,
)
from sidedeck.application.us_equity_calendar import (
    COMPLETE_CALENDAR_YEARS,
    expected_regular_sessions,
)


def _utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


def test_lse_hours_follow_london_daylight_saving() -> None:
    bst = XLON.session(date(2026, 10, 23))     # BST (UTC+1) until Sunday 25 October 2026
    gmt = XLON.session(date(2026, 10, 26))     # GMT
    assert bst is not None and gmt is not None
    assert (bst.open_utc, bst.close_utc) == (_utc(2026, 10, 23, 7), _utc(2026, 10, 23, 15, 30))
    assert (gmt.open_utc, gmt.close_utc) == (_utc(2026, 10, 26, 8), _utc(2026, 10, 26, 16, 30))
    assert XLON.regular_open == time(8, 0) and XLON.regular_close == time(16, 30)


def test_us_and_uk_dst_changes_are_independent() -> None:
    # US clocks moved on 8 March 2026, UK clocks on 29 March 2026: a four-hour gap that week.
    mid_march = date(2026, 3, 20)
    uk, us = XLON.session(mid_march), XNYS.session(mid_march)
    assert uk is not None and us is not None
    assert uk.open_utc == _utc(2026, 3, 20, 8) and us.open_utc == _utc(2026, 3, 20, 13, 30)
    april = date(2026, 4, 1)
    uk2, us2 = XLON.session(april), XNYS.session(april)
    assert uk2 is not None and us2 is not None
    assert uk2.open_utc == _utc(2026, 4, 1, 7) and us2.open_utc == _utc(2026, 4, 1, 13, 30)


def test_holidays_are_exchange_specific() -> None:
    assert not XLON.is_session(date(2026, 8, 31)) and XNYS.is_session(date(2026, 8, 31))
    assert XLON.is_session(date(2026, 9, 7)) and not XNYS.is_session(date(2026, 9, 7))
    assert XLON.is_session(date(2026, 11, 26)) and not XNYS.is_session(date(2026, 11, 26))
    assert not XLON.is_session(date(2026, 4, 6)) and XNYS.is_session(date(2026, 4, 6))
    assert not XLON.is_session(date(2026, 12, 28)) and XNYS.is_session(date(2026, 12, 28))


def test_exceptional_and_moved_closures() -> None:
    for day in (date(2022, 9, 19), date(2023, 5, 8), date(2022, 6, 2), date(2022, 6, 3)):
        assert not XLON.is_session(day)
    assert XLON.is_session(date(2022, 5, 30))  # statutory late-May Monday moved to 2 June


def test_half_days_close_continuous_trading_at_1230_london() -> None:
    eve = XLON.session(date(2026, 12, 24))
    nye = XLON.session(date(2026, 12, 31))
    assert eve is not None and eve.early_close and eve.close_utc == _utc(2026, 12, 24, 12, 30)
    assert nye is not None and nye.early_close
    assert XLON.sessions_between(date(2026, 12, 23), date(2026, 12, 31)) == (
        date(2026, 12, 23), date(2026, 12, 24), date(2026, 12, 29), date(2026, 12, 30),
        date(2026, 12, 31),
    )
    early = XLON.session(date(2023, 12, 22))  # 24 December 2023 was a Sunday
    assert early is not None and early.early_close


@pytest.mark.parametrize("year", sorted(UK_COVERED_YEARS))
def test_transcribed_table_matches_independent_rule_derivation(year: int) -> None:
    table = {d for d in UK_CLOSURES if d.year == year}
    expected = (derived_england_wales_bank_holidays(year) - UK_MOVED_AWAY) | {
        d for d in UK_EXCEPTIONAL_CLOSURES if d.year == year
    }
    assert table == expected
    assert {d for d in UK_HALF_DAYS if d.year == year} == derived_lse_half_days(year)


def test_easter_computus_known_dates() -> None:
    assert easter_sunday(2024) == date(2024, 3, 31)
    assert easter_sunday(2026) == date(2026, 4, 5)
    assert easter_sunday(2027) == date(2027, 3, 28)


def test_uncovered_years_fail_closed() -> None:
    with pytest.raises(CalendarError, match="does not cover 2028"):
        XLON.is_session(date(2028, 1, 4))
    with pytest.raises(CalendarError, match="does not cover 2021"):
        XLON.session(date(2021, 6, 1))
    with pytest.raises(CalendarError):
        XNYS.is_session(date(2027, 1, 4))


def test_is_open_boundaries_and_last_completed_session() -> None:
    assert not XLON.is_open(_utc(2026, 10, 23, 6, 59, 59))
    assert XLON.is_open(_utc(2026, 10, 23, 7, 0))
    assert XLON.is_open(_utc(2026, 10, 23, 15, 29, 59))
    assert not XLON.is_open(_utc(2026, 10, 23, 15, 30))
    assert not XLON.is_open(_utc(2026, 10, 24, 10))                    # Saturday
    assert XLON.last_completed_session(_utc(2026, 10, 23, 6, 30)) == date(2026, 10, 22)
    assert XLON.last_completed_session(_utc(2026, 10, 23, 15, 30)) == date(2026, 10, 23)
    assert XLON.last_completed_session(_utc(2026, 10, 26, 7)) == date(2026, 10, 23)
    with pytest.raises(CalendarError):
        XLON.is_open(datetime(2026, 10, 23, 9))                          # naive time


def test_xnys_matches_existing_us_calendar() -> None:
    for year in sorted(COMPLETE_CALENDAR_YEARS):
        assert XNYS.sessions_between(date(year, 1, 1), date(year, 12, 31)) == \
            expected_regular_sessions(date(year, 1, 1), date(year, 12, 31))


def test_exchange_mapping_and_validation() -> None:
    assert calendar_for_exchange("LSE") is XLON
    assert calendar_for_exchange("NASDAQ") is XNYS
    with pytest.raises(CalendarError):
        calendar_for_exchange("XETRA")
    with pytest.raises(CalendarError, match="weekend"):
        ExchangeCalendar("T", "t", "Europe/London", time(8), time(16, 30), time(12, 30),
                         frozenset({2026}), {date(2026, 10, 24): "x"}, {}, "S", "n")
    with pytest.raises(CalendarError, match="both closed and half day"):
        ExchangeCalendar("T", "t", "Europe/London", time(8), time(16, 30), time(12, 30),
                         frozenset({2026}), {date(2026, 12, 24): "x"},
                         {date(2026, 12, 24): "y"}, "S", "n")
    assert XLON.source_status == "TRANSCRIBED_RULE_CROSSCHECKED"
