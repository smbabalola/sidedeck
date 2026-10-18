"""Network-free tests for Tiingo-shaped EOD research-data validation."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from sidedeck.domain.tiingo_eod import (
    HistoricalDataError, assess_daily_coverage, parse_tiingo_eod,
)

NOW = datetime(2026, 10, 18, 16, 0, tzinfo=timezone.utc)


def sample(day: str = "2026-10-16") -> dict[str, object]:
    return {
        "date": day, "open": 100, "high": 105, "low": 97, "close": 102,
        "volume": 0, "adjOpen": 90, "adjHigh": 94.5, "adjLow": 87.3,
        "adjClose": 91.8, "adjVolume": 0, "divCash": 0.5,
        "splitFactor": 1,
    }


def parse(rows: list[dict[str, object]], ticker: str = "AAPL"):
    return parse_tiingo_eod(
        rows, ticker=ticker, collected_at=NOW, license_confirmed=True,
    )


def test_successful_private_eod_import_and_provenance() -> None:
    result = parse([sample("2026-10-15"), sample()])
    assert result.ticker == "AAPL"
    assert result.bars[0].day == date(2026, 10, 15)
    assert result.bars[-1].volume == Decimal("0")
    assert result.bars[-1].dividend == Decimal("0.5")
    assert result.source == "tiingo-eod"
    assert len(result.payload_sha256) == 64
    assert result.point_in_time_verified is False


def test_a_year_of_data_is_insufficient_for_five_year_gate() -> None:
    result = parse([sample("2026-10-16")])
    report = assess_daily_coverage(result, through=date(2026, 10, 18))
    assert report.status == "INSUFFICIENT_DEPTH"
    assert not report.point_in_time_verified


def test_earlier_data_without_exchange_calendar_is_unverified() -> None:
    result = parse([sample("2021-10-17"), sample("2026-10-16")])
    report = assess_daily_coverage(result, through=date(2026, 10, 18))
    assert report.status == "UNVERIFIED"


def test_verified_long_span_can_only_pass_with_complete_exchange_sessions() -> None:
    end = date(2026, 10, 16)
    start = date(2021, 10, 16)
    business = [start + timedelta(days=i) for i in range((end-start).days+1)
                if (start + timedelta(days=i)).weekday() < 5]
    rows = [sample(day.isoformat()) for day in business]
    dataset = parse(rows)
    reported = assess_daily_coverage(
        dataset, through=date(2026, 10, 18),
        verified_sessions=frozenset(business),
    )
    assert reported.status == "PASS_5Y_DAILY"
    assert reported.point_in_time_verified is False
    broken = parse(rows[:-1])
    assert assess_daily_coverage(
        broken, through=date(2026, 10, 18),
        verified_sessions=frozenset(business),
    ).status == "INSUFFICIENT_DEPTH"


@pytest.mark.parametrize("field,value", [
    ("high", 99),
    ("low", 106),
    ("close", 0),
    ("adjHigh", 80),
    ("volume", -1),
    ("divCash", -0.5),
    ("splitFactor", 0),
    ("adjClose", "NaN"),
    ("adjVolume", "Infinity"),
])
def test_invalid_values_fail_closed(field: str, value: object) -> None:
    row = sample()
    row[field] = value
    with pytest.raises(HistoricalDataError):
        parse([row])


def test_licence_required_and_reject_unapproved_ticker() -> None:
    with pytest.raises(HistoricalDataError):
        parse_tiingo_eod([sample()], ticker="AAPL", collected_at=NOW, license_confirmed=False)
    with pytest.raises(HistoricalDataError):
        parse([sample()], ticker="BTC")


def test_duplicate_dates_future_dates_and_missing_fields_fail() -> None:
    with pytest.raises(HistoricalDataError):
        parse([sample(), sample()])
    with pytest.raises(HistoricalDataError):
        parse([sample("2027-01-01")])
    with pytest.raises(HistoricalDataError):
        parse([{key: value for key, value in sample().items() if key != "adjOpen"}])


def test_no_network_auth_or_order_interface() -> None:
    import sidedeck.domain.tiingo_eod as module
    assert not any("token" in attr or "order" in attr or "broker" in attr for attr in dir(module))
    assert not hasattr(module, "fetch")


def test_rejects_naive_collection_time_and_missing_json() -> None:
    with pytest.raises(HistoricalDataError):
        parse_tiingo_eod(
            [sample()], ticker="AAPL",
            collected_at=datetime(2026, 10, 18, 16), license_confirmed=True,
        )
    with pytest.raises(HistoricalDataError):
        parse_tiingo_eod({}, ticker="AAPL", collected_at=NOW, license_confirmed=True)
