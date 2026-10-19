import copy

import pytest

from sidedeck.application.p5_historical_prices import PriceEvidenceError
from sidedeck.application.p5_valuation_evidence import valuation_evidence_report


def fundamental_rows():
    def eps(period, filed, value):
        return {"report_period": period, "filing_date": filed, "eps_ttm": value,
                "source": {"filed": filed, "unit": "USD/shares", "accession": period}}
    return {"ticker": "SOFI", "as_of": "2026-10-19", "metrics": {
        "annual_diluted_eps_ttm": [
            eps("2025-12-31", "2026-02-17", 0.39),
            eps("2024-12-31", "2025-02-24", 0.39),
            eps("2023-12-31", "2024-02-27", -0.36),
            eps("2022-12-31", "2023-03-01", -0.4),
        ]}}


def price_rows():
    return {"ticker": "SOFI", "currency": "USD", "price_basis": "split_adjusted_close",
            "corporate_actions_verified": False, "feed": "iex",
            "source": "https://data.alpaca.markets/v2/stocks/SOFI/bars",
            "records": [
                {"date": "2026-02-17", "close": 20, "source_id": "b1"},
                {"date": "2025-02-24", "close": 15, "source_id": "b2"},
                {"date": "2024-02-27", "close": 8, "source_id": "b3"},
            ]}


def test_evidence_report_counts_matches_without_inventing_pe():
    out = valuation_evidence_report(fundamental_rows(), price_rows())
    assert out["price_records"] == 3
    assert out["annual_eps_records"] == 4
    assert out["aligned_price_records"] == 3
    assert [item["status"] for item in out["matches"]] == [
        "P_E_VALIDATION_PENDING", "P_E_VALIDATION_PENDING",
        "P_E_NOT_MEANINGFUL", "PRICE_WINDOW_UNAVAILABLE",
    ]
    assert out["corporate_actions_verified"] is False
    assert out["historical_pe_validated"] is False
    assert all("illustrative_pe" not in row for row in out["matches"])
    assert out["assessment"] == "NO_GO"
    assert out["broker_execution"] == "DISABLED"


def test_invalid_price_provenance_fails_closed():
    prices = price_rows()
    prices["records"][0]["source_id"] = ""
    with pytest.raises(PriceEvidenceError):
        valuation_evidence_report(fundamental_rows(), prices)


def test_future_price_date_fails_closed():
    prices = price_rows()
    prices["records"].append({"date": "2026-10-20", "close": 1, "source_id": "future"})
    with pytest.raises(PriceEvidenceError):
        valuation_evidence_report(fundamental_rows(), prices)


def test_duplicate_prices_fail_closed():
    prices = price_rows()
    prices["records"].append(copy.deepcopy(prices["records"][0]))
    with pytest.raises(PriceEvidenceError):
        valuation_evidence_report(fundamental_rows(), prices)


def test_inconsistent_sec_source_fails_closed():
    fundamentals = fundamental_rows()
    fundamentals["metrics"]["annual_diluted_eps_ttm"][0]["source"]["filed"] = "2027-01-01"
    with pytest.raises(PriceEvidenceError):
        valuation_evidence_report(fundamentals, price_rows())
