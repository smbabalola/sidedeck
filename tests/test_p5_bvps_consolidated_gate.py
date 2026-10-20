import pytest
from sidedeck.application.p5_bvps_consolidated_gate import BVPSGateError, consolidate_bvps


def inputs():
    base = {"ticker": "SOFI", "as_of": "2026-10-19",
            "buffett_ready": False, "broker_execution": "DISABLED"}
    joined = {**base, "buffett_periods": 1, "observations": [
        {"report_period": "2026-06-30", "bvps_preview": 8.5841,
         "mapped_to_buffett": False, "equity_source": {"tag": "StockholdersEquity"},
         "shares_source": {"tag": "CommonStockSharesOutstanding"}}]}
    accounting = {**base, "observations": [
        {"report_period": "2026-06-30", "decision": "REQUIRES_REVIEW",
         "mapped_to_buffett": False}]}
    preferred = {**base, "periods": [
        {"report_period": "2026-06-30", "decision": "REQUIRES_REVIEW",
         "mapped_to_buffett": False, "preferred_balance_facts": [],
         "preferred_transaction_facts": [{"tag": "RedeemablePreferredStockDividends"}]}]}
    disclosure = {**base, "observations": [
        {"report_period": "2026-06-30", "decision": "REQUIRES_REVIEW",
         "mapped_to_buffett": False, "filing_disclosures": []}]}
    return joined, accounting, preferred, disclosure


def test_consolidation_is_no_go_with_lineage():
    result = consolidate_bvps(*inputs())
    assert result["total_periods"] == 1
    assert result["requires_review_periods"] == 1
    assert result["approved_periods"] == 0
    assert result["periods"][0]["preferred_transaction_fact_count"] == 1
    assert result["periods"][0]["approved_for_buffett"] is False


def test_reject_conflicting_periods():
    reports = list(inputs())
    reports[2]["periods"][0]["report_period"] = "2025-06-30"
    with pytest.raises(BVPSGateError, match="different historical periods"):
        consolidate_bvps(*reports)


def test_reject_spurious_approval():
    reports = list(inputs())
    reports[1]["observations"][0]["decision"] = "APPROVED"
    with pytest.raises(BVPSGateError, match="prior approval"):
        consolidate_bvps(*reports)
