import pytest
from sidedeck.application.p5_equity_consistency import audit_equity_consistency


def sample():
    safe = {"ticker": "SOFI", "as_of": "2026-10-19", "buffett_ready": False,
            "broker_execution": "DISABLED"}
    bridge = {**safe, "periods": 1, "observations": [{
        "report_period": "2026-06-30", "mapped_to_buffett": False,
        "matching_capital_facts": [
            {"tag": "StockholdersEquity", "value": 100},
            {"tag": "CommonStockSharesOutstanding", "value": 10},
            {"tag": "CommonStockSharesIssued", "value": 12}]}]}
    joined = {**safe, "buffett_periods": 1, "observations": [
        {"report_period": "2026-06-30", "bvps_preview": 10,
         "mapped_to_buffett": False}]}
    return bridge, joined


def test_consistent_values_not_approved():
    report = audit_equity_consistency(*sample())
    assert report["periods_with_diagnostic_issues"] == 0
    assert report["observations"][0]["consistent_source_fact_values"] is True
    assert report["approved_periods"] == 0


def test_conflicting_same_accession_equity_detected():
    bridge, joined = sample()
    bridge["observations"][0]["matching_capital_facts"].append(
        {"tag": "StockholdersEquity", "value": 120})
    report = audit_equity_consistency(bridge, joined)
    assert "CONFLICTING_SAME_ACCESSION_VALUES" in report["observations"][0]["issue_codes"]


def test_outstanding_greater_than_issued_detected():
    bridge, joined = sample()
    bridge["observations"][0]["matching_capital_facts"][2]["value"] = 8
    assert "OUTSTANDING_EXCEEDS_ISSUED" in audit_equity_consistency(bridge, joined)["observations"][0]["issue_codes"]


def test_preview_mismatch_detected():
    bridge, joined = sample()
    joined["observations"][0]["bvps_preview"] = 9
    assert "BVPS_PREVIEW_NOT_RECONCILED" in audit_equity_consistency(bridge, joined)["observations"][0]["issue_codes"]


def test_reject_inconsistent_cutoff():
    bridge, joined = sample()
    joined["as_of"] = "2026-10-18"
    with pytest.raises(ValueError, match="cutoff"):
        audit_equity_consistency(bridge, joined)
