import pytest
from sidedeck.application.p5_filing_disclosure_review import disclosure_review


def inputs():
    joined = {"ticker": "SOFI", "as_of": "2026-10-19",
              "buffett_ready": False, "broker_execution": "DISABLED",
              "buffett_periods": 2, "observations": [
                  {"report_period": "2026-06-30", "bvps_preview": 8.58, "mapped_to_buffett": False},
                  {"report_period": "2025-03-31", "bvps_preview": 5.0, "mapped_to_buffett": False}]}
    raw = {"cik": 1818874, "facts": {"us-gaap": {
        "CommonStockSharesOutstanding": {"units": {"shares": [
            {"end": "2026-06-30", "filed": "2026-08-06", "val": 1290312404}]}}}}}
    return joined, raw


def test_primary_filing_corrobates_shares_but_never_auto_approves():
    joined, raw = inputs()
    output = disclosure_review(joined, raw)
    assert output["approved_periods"] == 0
    assert output["review_required"] == 2
    assert output["observations"][0]["2026_share_count_corrobated"] is True
    assert output["observations"][1]["share_basis_status"] == "NOT_VERIFIED"
    assert all(x["mapped_to_buffett"] is False for x in output["observations"])


def test_future_share_fact_does_not_corrobate():
    joined, raw = inputs()
    raw["facts"]["us-gaap"]["CommonStockSharesOutstanding"]["units"]["shares"][0]["filed"] = "2027-01-01"
    assert disclosure_review(joined, raw)["observations"][0]["2026_share_count_corrobated"] is False


def test_approval_elevation_rejected():
    joined, raw = inputs()
    joined["buffett_ready"] = True
    with pytest.raises(ValueError, match="approval"):
        disclosure_review(joined, raw)
