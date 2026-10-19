import pytest

from sidedeck.application.p5_historical_prices import (
    PriceEvidenceError, compare_annual_eps_prices,
)


def fundamentals():
    return {"ticker": "SOFI", "as_of": "2025-05-01", "metrics": {
        "annual_diluted_eps_ttm": [{
            "report_period": "2024-12-31", "filing_date": "2025-02-01",
            "eps_ttm": 0.5, "source": {"filed": "2025-02-01", "accession": "SEC1"},
        }],
    }}


def prices():
    return {"ticker": "SOFI", "currency": "USD", "price_basis": "split_adjusted_close",
            "corporate_actions_verified": True, "source": "https://example.org/market",
            "records": [{"date": "2025-02-03", "close": 12, "source_id": "p1"}]}


def test_historical_price_preview_stays_no_go():
    report = compare_annual_eps_prices(fundamentals(), prices())
    assert report["valuation_preview"][0]["illustrative_pe"] == 24
    assert report["valuation_preview"][0]["price_date"] == "2025-02-03"
    assert report["assessment"] == "NO_GO"
    assert report["broker_execution"] == "DISABLED"


def test_wrong_currency_fails_closed():
    p = prices()
    p["currency"] = "GBP"
    with pytest.raises(PriceEvidenceError):
        compare_annual_eps_prices(fundamentals(), p)


def test_future_or_duplicate_price_rejected():
    p = prices()
    p["records"].append({"date": "2025-05-02", "close": 10, "source_id": "future"})
    with pytest.raises(PriceEvidenceError):
        compare_annual_eps_prices(fundamentals(), p)
    p = prices()
    p["records"].append(p["records"][0].copy())
    with pytest.raises(PriceEvidenceError):
        compare_annual_eps_prices(fundamentals(), p)


def test_nonpositive_eps_does_not_invent_pe():
    f = fundamentals()
    f["metrics"]["annual_diluted_eps_ttm"][0]["eps_ttm"] = -0.5
    assert compare_annual_eps_prices(f, prices())["valuation_preview"] == []


def test_missing_price_source_rejected():
    p = prices()
    del p["records"][0]["source_id"]
    with pytest.raises(PriceEvidenceError):
        compare_annual_eps_prices(fundamentals(), p)
