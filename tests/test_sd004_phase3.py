from datetime import date, datetime

import pytest

from sidedeck.application.p5_sec_publication import SecPublication, first_eligible_close
from sidedeck.application.p5_yahoo_history import YahooHistoryUnavailable, parse_yahoo_csv
from sidedeck.application.us_equity_calendar import (
    expected_regular_sessions,
    validate_session_coverage,
)


def test_2026_calendar_excludes_labor_day_and_validates_59_bar_window() -> None:
    sessions = expected_regular_sessions(date(2026, 7, 29), date(2026, 10, 20))
    assert len(sessions) == 59
    assert date(2026, 9, 7) not in sessions
    assert date(2026, 10, 12) in sessions
    coverage = validate_session_coverage(sessions, start=sessions[0], end=sessions[-1])
    assert coverage.status == "VALIDATED"
    assert coverage.missing == ()


@pytest.mark.parametrize("accepted", ["2026-07-29T16:04:53-04:00", "2026-07-29T16:08:01-04:00"])
def test_sec_after_close_is_first_eligible_on_july_30(accepted: str) -> None:
    filing = SecPublication("test", "8-K", datetime.fromisoformat(accepted), "https://www.sec.gov/")
    assert first_eligible_close(filing) == date(2026, 7, 30)


def test_sec_requires_timezone() -> None:
    filing = SecPublication("test", "10-K", datetime(2026, 7, 29, 16, 8, 1), "https://www.sec.gov/")
    with pytest.raises(ValueError, match="timezone-aware"):
        first_eligible_close(filing)


def test_yahoo_parser_uses_close_and_marks_provenance_unverified() -> None:
    parsed = parse_yahoo_csv(
        "Date,Close,Adj Close\n2026-07-30,510.00,509.00\n",
        ticker="MSFT", source_url="https://finance.yahoo.com/quote/MSFT/history/", cutoff=date(2026, 10, 20),
    )
    assert parsed["records"][0]["close"] == "510.00"
    assert parsed["adj_close_present"] is True
    assert parsed["provenance_verified"] is False
    assert parsed["adjustment"] == "unknown"


def test_yahoo_parser_rejects_weekend() -> None:
    with pytest.raises(YahooHistoryUnavailable, match="regular trading session"):
        parse_yahoo_csv(
            "Date,Close\n2026-08-01,510.00\n", ticker="MSFT", source_url="https://example.test", cutoff=date(2026, 10, 20)
        )


def test_yahoo_parser_rejects_exchange_holiday() -> None:
    with pytest.raises(YahooHistoryUnavailable, match="regular trading session"):
        parse_yahoo_csv(
            "Date,Close\n2026-09-07,510.00\n", ticker="MSFT", source_url="https://example.test", cutoff=date(2026, 10, 20)
        )
