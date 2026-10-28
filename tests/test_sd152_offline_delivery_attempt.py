"""Offline delivery readiness must never imply provider transport or receipt."""
import pytest

from sidedeck.application.sd152_offline_delivery_attempt import assess_offline_delivery_attempt


def _outbox():
    return {
        "schema": "sidedeck.sd152.offline-notification-outbox/1",
        "delivery_status": "NOT_CONFIGURED",
        "external_notification_confirmed": False,
        "dispatch_allowed": False,
        "safe_to_trade": False,
        "clear_halt_allowed": False,
        "execution_release": "ETORO_DEMO_NOT_RELEASED",
        "observations": 2,
    }


@pytest.mark.parametrize(("provider", "operator"), [
    (False, False), (True, False), (False, True), (True, True),
])
def test_no_caller_claim_can_attempt_delivery(provider, operator):
    result = assess_offline_delivery_attempt(
        _outbox(), provider_configured=provider, operator_authorized=operator)
    assert result["attempt_status"] == "BLOCKED_BEFORE_DISPATCH"
    assert result["provider_attempted"] is False
    assert result["provider_receipt_verified"] is False
    assert result["retry_dispatch_allowed"] is False
    assert result["operator_authorized"] is False
    assert result["execution_release"] == "ETORO_DEMO_NOT_RELEASED"


@pytest.mark.parametrize("change", [
    {"delivery_status": "SENT"},
    {"external_notification_confirmed": True},
    {"dispatch_allowed": True},
    {"observations": True},
    {"execution_release": "RELEASED"},
])
def test_forged_delivery_evidence_never_produces_receipt(change):
    result = assess_offline_delivery_attempt({**_outbox(), **change})
    assert "OUTBOX_EVIDENCE_INVALID" in result["reasons"]
    assert result["provider_attempted"] is False
    assert result["provider_receipt_verified"] is False
