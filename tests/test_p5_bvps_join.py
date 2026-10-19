import pytest

from sidedeck.application.p5_bvps_join import BVPSJoinError, reconcile_bvps


def fixtures():
    source = {"ticker": "SOFI", "as_of": "2026-10-19",
              "complete_period_count": 2, "periods": [
                  {"report_period": "2026-06-30", "available_from": "2026-08-06"},
                  {"report_period": "2026-03-31", "available_from": "2026-05-07"}]}
    equity = {"accession": "0001818874-26-000001", "filed": "2026-08-06",
              "tag": "StockholdersEquity", "unit": "USD"}
    shares = {"accession": "0001818874-26-000001", "filed": "2026-08-06",
              "tag": "CommonStockSharesOutstanding", "unit": "shares"}
    evidence = {"as_of": "2026-10-19", "matched_periods": 1,
                "buffett_ready": False, "broker_execution": "DISABLED",
                "observations": [{"report_period": "2026-06-30",
                                  "available_from": "2026-08-06",
                                  "book_value_per_share_preview": 8.5841,
                                  "equity_source": equity,
                                  "shares_source": shares,
                                  "approval": "UNVERIFIED"}]}
    return source, evidence


def test_join_preserves_preview_but_never_maps_to_buffett():
    coverage, evidence = fixtures()
    result = reconcile_bvps(coverage, evidence)
    assert result["buffett_periods"] == 2
    assert result["bvps_matched_periods"] == 1
    assert result["observations"][0]["bvps_preview"] == 8.5841
    assert result["observations"][1]["bvps_preview"] is None
    assert all(x["mapped_to_buffett"] is False for x in result["observations"])
    assert result["buffett_ready"] is False
    assert result["broker_execution"] == "DISABLED"


def test_wrong_asof_fails_closed():
    coverage, evidence = fixtures()
    evidence["as_of"] = "2026-10-20"
    with pytest.raises(BVPSJoinError, match="inconsistent"):
        reconcile_bvps(coverage, evidence)


def test_mismatched_accession_fails_closed():
    coverage, evidence = fixtures()
    evidence["observations"][0]["shares_source"]["accession"] = "0001818874-26-000002"
    with pytest.raises(BVPSJoinError, match="unsupported"):
        reconcile_bvps(coverage, evidence)


def test_unverified_input_cannot_claim_readiness():
    coverage, evidence = fixtures()
    evidence["buffett_ready"] = True
    with pytest.raises(BVPSJoinError, match="unguarded"):
        reconcile_bvps(coverage, evidence)
