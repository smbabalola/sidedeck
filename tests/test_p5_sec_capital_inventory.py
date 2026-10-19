import pytest
from sidedeck.application.p5_sec_capital_inventory import capital_inventory


def test_capital_inventory_preserves_filed_evidence_without_approval():
    raw = {"cik": 1818874, "facts": {"us-gaap": {
        "PreferredStockValue": {"units": {"USD": [
            {"end": "2025-12-31", "filed": "2026-02-17", "val": 100,
             "accn": "0001818874-26-000012", "form": "10-K"},
            {"end": "2026-12-31", "filed": "2027-02-17", "val": 0,
             "accn": "0001818874-27-000012", "form": "10-K"},
        ]}},
        "CommonStockSharesOutstanding": {"units": {"shares": [
            {"end": "2025-12-31", "filed": "2026-02-17", "val": 500,
             "accn": "0001818874-26-000012", "form": "10-K"}]}}
    }}}
    result = capital_inventory(raw, "2026-10-19")
    assert result["capital_observation_count"] == 2
    assert {r["tag"] for r in result["capital_observations"]} == {
        "PreferredStockValue", "CommonStockSharesOutstanding"}
    assert result["preferred_status"] == "UNDETERMINED"
    assert result["approved_bvps_periods"] == 0
    assert result["broker_execution"] == "DISABLED"


def test_empty_capital_tags_do_not_mean_zero_preferred():
    result = capital_inventory({"cik": 1818874, "facts": {}}, "2026-10-19")
    assert result["capital_observation_count"] == 0
    assert result["preferred_status"] == "UNDETERMINED"


def test_other_issuer_rejected():
    with pytest.raises(ValueError, match="SOFI"):
        capital_inventory({"cik": 123, "facts": {}}, "2026-10-19")
