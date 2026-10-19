import json

import pytest

from sidedeck.bridges.filed_fundamentals import FundamentalsDataError, verified_fundamentals


def sample():
    return {
        "ticker": "SOFI",
        "records": [
            {
                "report_period": f"2025-{quarter:02d}-01",
                "filing_date": f"2025-{quarter:02d}-15",
                "source_url": "https://www.sec.gov/Archives/edgar/data/1/filing",
                "period": "ttm",
                "return_on_equity": 0.1,
            }
            for quarter in (1, 2, 3, 4)
        ],
    }


def store(tmp_path, payload):
    file = tmp_path / "filings.json"
    file.write_text(json.dumps(payload), encoding="utf-8")
    return file


def test_valid_filings_return_latest_first(tmp_path):
    actual = verified_fundamentals(store(tmp_path, sample()), "SOFI", "2025-12-01")
    assert len(actual) == 4
    assert actual[0]["filing_date"] == "2025-04-15"
    assert "source_url" not in actual[0]


def test_missing_filing_provenance_fails_closed(tmp_path):
    data = sample()
    del data["records"][0]["source_url"]
    with pytest.raises(FundamentalsDataError):
        verified_fundamentals(store(tmp_path, data), "SOFI", "2025-12-01")


def test_future_filings_not_included(tmp_path):
    with pytest.raises(FundamentalsDataError, match="fewer than four"):
        verified_fundamentals(store(tmp_path, sample()), "SOFI", "2025-03-20")


def test_ticker_mismatch_rejected(tmp_path):
    with pytest.raises(FundamentalsDataError, match="ticker mismatch"):
        verified_fundamentals(store(tmp_path, sample()), "AAPL", "2025-12-01")


def test_fake_metric_rejected(tmp_path):
    data = sample()
    data["records"][0]["predicted_revenue"] = 40000000
    with pytest.raises(FundamentalsDataError):
        verified_fundamentals(store(tmp_path, data), "SOFI", "2025-12-01")
