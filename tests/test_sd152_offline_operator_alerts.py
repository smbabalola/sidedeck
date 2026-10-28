"""Offline operator alerts are never an execution or HALT-reset authority."""
from sidedeck.application.sd152_offline_operator_alerts import evaluate_offline_alerts


def healthy():
    return {
        "schema": "sidedeck.sd152.offline-fence-health/1",
        "state": "IDLE", "alerts": [], "broker_route": "SIMULATED_LOCAL",
        "execution_release": "ETORO_DEMO_NOT_RELEASED",
    }


def dossier():
    return {"uncertain_orders": [], "execution_release": "ETORO_DEMO_NOT_RELEASED"}


def test_clean_evidence_is_observation_only_and_never_release():
    result = evaluate_offline_alerts(healthy(), dossier())
    assert result["status"] == "OBSERVATION_ONLY"
    assert result["incidents"] == []
    assert result["safe_to_trade"] is False
    assert result["automatic_recovery_allowed"] is False
    assert result["clear_halt_allowed"] is False


def test_stale_running_worker_requires_attention():
    state = {**healthy(), "state": "RUNNING",
             "alerts": ["EXCLUSIVE_WORKER_ACTIVE",
                        "STALE_RUNNING_HEARTBEAT_RECONCILIATION_REQUIRED"]}
    result = evaluate_offline_alerts(state, dossier())
    assert "STALE_RUNNING_HEARTBEAT_RECONCILIATION_REQUIRED" in result["incidents"]
    assert result["status"] == "ATTENTION_REQUIRED"


def test_uncertain_order_and_unresolved_fence_block_clean_report():
    state = {**healthy(), "state": "UNRESOLVED",
             "alerts": ["MANUAL_RECONCILIATION_REQUIRED_NO_AUTOMATIC_TAKEOVER"]}
    result = evaluate_offline_alerts(state, {**dossier(), "uncertain_orders": [{"id": "synthetic"}]})
    assert "FENCE_UNRESOLVED" in result["incidents"]
    assert "UNCERTAIN_ORDER_REQUIRES_MANUAL_RECONCILIATION" in result["incidents"]
    assert result["safe_to_trade"] is False


def test_missing_or_forged_inputs_fail_closed():
    for state, record in (
        ({}, {}),
        ({**healthy(), "execution_release": "RELEASED"}, dossier()),
        ({**healthy(), "broker_route": "ETORO_REAL"}, dossier()),
        ({**healthy(), "alerts": ["UNKNOWN_PROVIDER_SIGNAL"]}, dossier()),
        (healthy(), {**dossier(), "uncertain_orders": "empty"}),
    ):
        result = evaluate_offline_alerts(state, record)
        assert result["status"] == "ATTENTION_REQUIRED"
        assert result["incidents"]
        assert not result["safe_to_trade"]
