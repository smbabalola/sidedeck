import pytest

from sidedeck.application.p5_bvps_accounting_review import review_bvps


def test_bvps_review_does_not_approve_preliminary_values():
    joined = {"ticker": "SOFI", "as_of": "2026-10-19",
              "buffett_ready": False, "broker_execution": "DISABLED",
              "observations": [
                  {"report_period": "2026-06-30", "bvps_preview": 8.5841},
                  {"report_period": "2026-03-31", "bvps_preview": None},
              ]}
    result = review_bvps(joined, {"cik": 1818874})
    assert result["approved_periods"] == 0
    assert result["requires_review_periods"] == 1
    assert result["rejected_periods"] == 1
    assert all(row["mapped_to_buffett"] is False for row in result["observations"])
    assert result["broker_execution"] == "DISABLED"


def test_reject_wrong_company():
    joined = {"ticker": "SOFI", "as_of": "2026-10-19",
              "buffett_ready": False, "broker_execution": "DISABLED",
              "observations": []}
    with pytest.raises(ValueError, match="issuer"):
        review_bvps(joined, {"cik": 1})


def test_reject_elevated_gate():
    joined = {"ticker": "SOFI", "as_of": "2026-10-19",
              "buffett_ready": True, "broker_execution": "DISABLED",
              "observations": []}
    with pytest.raises(ValueError, match="unapproved"):
        review_bvps(joined, {"cik": 1818874})
