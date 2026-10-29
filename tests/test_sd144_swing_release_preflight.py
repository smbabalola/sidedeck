"""SWING admission preflight never turns fabricated data into execution authority."""
from sidedeck.application.sd144_swing_release_preflight import swing_strategy_release_preflight


def test_missing_strategy_evidence_identifies_all_external_gates():
    report = swing_strategy_release_preflight(None)
    assert report["status"] == "BLOCKED_EXTERNAL"
    assert "STRATEGY_EVIDENCE_MISSING" in report["missing_evidence"]
    assert "MARKET_DATA_RIGHTS_UNVERIFIED" in report["missing_evidence"]
    assert report["safe_to_trade"] is False


def test_too_few_oos_trades_rejected_despite_owner_claims():
    report = swing_strategy_release_preflight({
        "track": "SWING", "source": "GENUINE_HISTORICAL",
        "locked_oos": True, "qualified_oos_trades": 29,
        "reproducible_evidence_ref": "fixture-only",
    }, market_data_rights_verified=True, broker_execution_price_verified=True,
       independent_admission_verified=True)
    assert "QUALIFIED_OOS_TRADES_BELOW_FLOOR" in report["missing_evidence"]
    assert report["broker_execution_allowed"] is False


def test_complete_claims_are_still_not_an_order_grant():
    report = swing_strategy_release_preflight({
        "track": "SWING", "source": "GENUINE_HISTORICAL",
        "locked_oos": True, "qualified_oos_trades": 30,
        "reproducible_evidence_ref": "fixture-only",
    }, market_data_rights_verified=True, broker_execution_price_verified=True,
       independent_admission_verified=True)
    assert report["status"] == "READY_FOR_SEPARATE_RELEASE_REVIEW"
    assert report["strategy_admitted_by_this_report"] is False
    assert report["safe_to_trade"] is False
    assert report["execution_release"] == "ETORO_DEMO_NOT_RELEASED"
