"""Digest never grants broker or HALT authority."""
from sidedeck.application.sd152_offline_alert_digest import build_offline_alert_digest


def good():
    return {
        "schema": "sidedeck.sd152.offline-operator-alerts/1",
        "status": "ATTENTION_REQUIRED",
        "incidents": ["FENCE_UNRESOLVED", "HEARTBEAT_CLOCK_UNVERIFIED"],
        "safe_to_trade": False, "automatic_recovery_allowed": False,
        "clear_halt_allowed": False,
        "execution_release": "ETORO_DEMO_NOT_RELEASED",
    }


def test_stable_digest_across_order_and_duplicates():
    first = build_offline_alert_digest(good())
    second = build_offline_alert_digest(
        {**good(), "incidents": [
            "HEARTBEAT_CLOCK_UNVERIFIED", "FENCE_UNRESOLVED",
            "FENCE_UNRESOLVED",
        ]},
    )
    assert first == second
    assert first["operator_action"] == "MANUAL_REVIEW_ONLY"
    assert first["delivery_status"] == "NOT_CONFIGURED"
    assert first["safe_to_trade"] is False


def test_clean_digest_still_never_releases_execution():
    clean = {**good(), "status": "OBSERVATION_ONLY", "incidents": []}
    result = build_offline_alert_digest(clean)
    assert result["severity"] == "INFORMATIONAL"
    assert result["clear_halt_allowed"] is False


def test_forged_or_invalid_reports_fail_closed():
    bad = (
        {**good(), "safe_to_trade": True},
        {**good(), "execution_release": "RELEASED"},
        {**good(), "incidents": ["private identifier: 123"]},
        {**good(), "status": "OBSERVATION_ONLY"},
        {**good(), "incidents": "none"},
        {},
    )
    for case in bad:
        result = build_offline_alert_digest(case)
        assert result["incidents"] == ["OPERATOR_ALERT_REPORT_INVALID"]
        assert result["severity"] == "ACTION_REQUIRED"
        assert result["delivery_status"] == "NOT_CONFIGURED"
