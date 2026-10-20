"""Synthetic fixtures only; not SOFI observations."""
from decimal import Decimal

import pytest

from sidedeck.application.p5_historical_prices import PriceEvidenceError
from sidedeck.application.p5_market_cap_evidence import market_cap_evidence

Q2_26 = "0000000001-26-000054"
FY_25 = "0000000001-26-000013"


def _facts(share_rows=None, q2_ytd=23):
    income = [
        {"start": "2025-01-01", "end": "2025-06-30", "val": 20, "accn": "0000000001-25-000180",
         "form": "10-Q", "filed": "2025-08-07"},
        {"start": "2025-01-01", "end": "2025-12-31", "val": 40, "accn": FY_25,
         "form": "10-K", "filed": "2026-02-17"},
        {"start": "2026-01-01", "end": "2026-06-30", "val": q2_ytd, "accn": Q2_26,
         "form": "10-Q", "filed": "2026-08-06"},
    ]
    equity = [
        {"end": "2025-12-31", "val": 900, "accn": Q2_26, "form": "10-Q", "filed": "2026-08-06"},
        {"end": "2026-06-30", "val": 1000, "accn": Q2_26, "form": "10-Q", "filed": "2026-08-06"},
        {"end": "2025-12-31", "val": 900, "accn": FY_25, "form": "10-K", "filed": "2026-02-17"},
    ]
    shares = share_rows if share_rows is not None else [
        {"end": "2026-07-31", "val": 1000, "accn": Q2_26, "form": "10-Q", "filed": "2026-08-06"},
        {"end": "2026-01-30", "val": 900, "accn": FY_25, "form": "10-K", "filed": "2026-02-17"},
    ]
    return {"facts": {
        "us-gaap": {"NetIncomeLoss": {"units": {"USD": income}},
                    "StockholdersEquity": {"units": {"USD": equity}}},
        "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": shares}}},
    }}


def _prices(records=None):
    return {"ticker": "TEST", "currency": "USD", "price_basis": "split_adjusted_close",
            "feed": "iex", "source": "https://data.alpaca.markets/v2/stocks/TEST/bars",
            "records": records if records is not None else [
                {"date": "2026-08-06", "close": 99.0, "source_id": "same-day"},
                {"date": "2026-08-07", "close": 12.5, "source_id": "next-session"},
                {"date": "2026-02-18", "close": 10.0, "source_id": "fy"},
            ]}


def _row(report, period):
    return next(r for r in report["observations"] if r["report_period"] == period)


def test_market_cap_uses_next_session_close_after_filing():
    report = market_cap_evidence(_facts(), _prices(), "2026-10-19", "TEST")
    row = _row(report, "2026-06-30")
    assert row["price_date"] == "2026-08-07"  # same-day bar may precede release
    assert row["price_source_id"] == "next-session"
    assert row["shares_outstanding"] == 1000
    assert row["shares_as_of"] == "2026-07-31"
    assert Decimal(row["market_cap_candidate"]) == Decimal("12500")
    assert row["available_from"] == "2026-08-07"
    assert row["status"] == "MARKET_CAP_CANDIDATE_UNVALIDATED"
    assert row["included_in_input"] is False
    assert report["market_cap_validated"] is False
    assert report["validation_gaps"]
    assert report["assessment"] == "NO_GO"


def test_pe_is_never_numeric_and_reflects_earnings_sign():
    row = _row(market_cap_evidence(_facts(), _prices(), "2026-10-19", "TEST"), "2026-06-30")
    assert row["pe_status"] == "P_E_VALIDATION_PENDING"
    assert "price_to_earnings_ratio" not in row
    loss = _row(market_cap_evidence(_facts(q2_ytd=-100), _prices(), "2026-10-19", "TEST"),
                "2026-06-30")
    assert loss["pe_status"] == "P_E_NOT_MEANINGFUL"


def test_missing_price_window_is_reported_not_filled():
    prices = _prices([{"date": "2026-02-18", "close": 10.0, "source_id": "fy"}])
    row = _row(market_cap_evidence(_facts(), prices, "2026-10-19", "TEST"), "2026-06-30")
    assert row["status"] == "PRICE_WINDOW_UNAVAILABLE"
    assert row["market_cap_candidate"] is None


def test_future_filings_are_excluded():
    report = market_cap_evidence(_facts(), _prices([
        {"date": "2026-02-18", "close": 10.0, "source_id": "fy"}]), "2026-03-01", "TEST")
    assert [r["report_period"] for r in report["observations"]] == ["2025-12-31"]


def test_multiple_share_classes_in_one_filing_block_candidate():
    shares = [
        {"end": "2026-07-31", "val": 1000, "accn": Q2_26, "form": "10-Q", "filed": "2026-08-06"},
        {"end": "2026-07-31", "val": 50, "accn": Q2_26, "form": "10-Q", "filed": "2026-08-06"},
    ]
    row = _row(market_cap_evidence(_facts(shares), _prices(), "2026-10-19", "TEST"), "2026-06-30")
    assert row["status"] == "MULTIPLE_SHARE_COUNTS"
    assert row["market_cap_candidate"] is None


def test_price_file_is_validated_with_shared_loader():
    prices = _prices()
    prices["ticker"] = "OTHER"
    with pytest.raises(PriceEvidenceError, match="ticker"):
        market_cap_evidence(_facts(), prices, "2026-10-19", "TEST")
