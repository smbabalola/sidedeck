"""Untrusted identity claims cannot authorize offline incident acknowledgement."""
import pytest

from sidedeck.application.sd152_operator_authorization import assess_operator_ack_authorization


@pytest.mark.parametrize("claim", [
    None,
    {"authenticated": True, "role": "operator"},
    {"verified": True, "issuer": "self"},
    {"signature": "fake", "permissions": ["ACKNOWLEDGE", "TRADE"]},
])
def test_operator_identity_claims_never_grant_authorization(claim):
    ack = {
        "schema": "sidedeck.sd152.offline-operator-ack/1",
        "execution_release": "ETORO_DEMO_NOT_RELEASED",
        "safe_to_trade": False,
        "clear_halt_allowed": False,
        "incident_resolved": False,
        "external_notification_confirmed": False,
        "delivery_status": "NOT_CONFIGURED",
    }
    result = assess_operator_ack_authorization(ack, claim)
    assert result["authorization_status"] == "DENIED"
    assert result["operator_identity_verified"] is False
    assert result["acknowledgement_authorized"] is False
    assert result["notification_dispatch_allowed"] is False
    assert result["safe_to_trade"] is False
    assert result["clear_halt_allowed"] is False


def test_invalid_acknowledgement_does_not_establish_identity():
    result = assess_operator_ack_authorization({"execution_release": "RELEASED"})
    assert "OPERATOR_ACKNOWLEDGEMENT_INVALID" in result["incidents"]
    assert result["authorization_status"] == "DENIED"
