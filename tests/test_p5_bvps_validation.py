import pytest
from sidedeck.application.p5_bvps_validation import validate_bvps


def inputs():
    source = {"ticker": "SOFI", "as_of": "2026-10-19",
              "complete_period_count": 1,
              "periods": [{"report_period": "2026-06-30", "available_from": "2026-08-06"}]}
    equity = {"accession": "0001818874-26-000001", "filed": "2026-08-06",
              "tag": "StockholdersEquity", "unit": "USD"}
    shares = {"accession": "0001818874-26-000001", "filed": "2026-08-06",
              "tag": "CommonStockSharesOutstanding", "unit": "shares"}
    bvps = {"as_of": "2026-10-19", "matched_periods": 1,
            "buffett_ready": False, "broker_execution": "DISABLED",
            "observations": [{"report_period": "2026-06-30",
                              "available_from": "2026-08-06",
                              "book_value_per_share_preview": 8.58,
                              "equity_source": equity, "shares_source": shares,
                              "approval": "UNVERIFIED"}]}
    capital = {"cik": 1818874, "as_of": "2026-10-19",
               "capital_observations": []}
    raw = {"cik": 1818874, "facts": {"us-gaap": {
        "CommonStockSharesOutstanding": {"units": {"shares": []}}}}}
    return source, bvps, capital, raw


def test_consolidated_review_holds_all_previews_out_of_scoring():
    report = validate_bvps(*inputs())
    assert report["reviewed_periods"] == 1
    assert report["requires_review_periods"] == 1
    assert report["approved_periods"] == 0
    assert report["observations"][0]["mapped_to_buffett"] is False
    assert "COMMON_EQUITY_NUMERATOR_NOT_VERIFIED" in report["observations"][0]["evidence_gaps"]
    assert report["broker_execution"] == "DISABLED"


def test_reject_wrong_capital_cutoff():
    coverage, bvps, capital, raw = inputs()
    capital["as_of"] = "2027-01-01"
    with pytest.raises(ValueError, match="mismatch"):
        validate_bvps(coverage, bvps, capital, raw)
