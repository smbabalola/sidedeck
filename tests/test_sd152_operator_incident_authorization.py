"""Offline verifier harness proves tenant/role/expiry enforcement, not an IdP."""
from datetime import UTC, datetime, timedelta

import pytest

from sidedeck.application.sd152_operator_identity_boundary import (
    OperatorAuthenticationDenied, VerifiedOperator,
)
from sidedeck.application.sd152_operator_incident_authorization import authorize_operator_incident


class FakeVerifier:
    def __init__(self, principal):
        self.principal = principal

    def verify(self, token, *, audience, at):
        assert audience == "sidedeck-ops"
        return self.principal


def _principal(now, *, tenant="tenant-a", roles=frozenset({"incident:acknowledge"}), expiry=60):
    return VerifiedOperator("user-1", "fixture-only", tenant, roles,
                            now + timedelta(seconds=expiry))


def test_default_identity_verifier_denies_all_incident_access():
    with pytest.raises(OperatorAuthenticationDenied):
        authorize_operator_incident("self-asserted", audience="sidedeck-ops",
                                    tenant="tenant-a", incident_digest="a" * 64,
                                    at=datetime.now(UTC))


@pytest.mark.parametrize("overrides", [
    {"tenant": "tenant-b"},
    {"roles": frozenset({"trading:approve"})},
    {"expiry": 0},
    {"expiry": -10},
])
def test_offline_fixture_denies_wrong_tenant_role_or_expiry(overrides):
    now = datetime(2026, 10, 28, 13, tzinfo=UTC)
    p = _principal(now, **overrides)
    with pytest.raises(OperatorAuthenticationDenied):
        authorize_operator_incident("fixture", audience="sidedeck-ops",
                                    tenant="tenant-a", incident_digest="a" * 64,
                                    at=now, verifier=FakeVerifier(p))


def test_verified_shape_is_still_only_offline_fixture_not_real_idp():
    now = datetime(2026, 10, 28, 13, tzinfo=UTC)
    result = authorize_operator_incident(
        "fixture", audience="sidedeck-ops", tenant="tenant-a",
        incident_digest="a" * 64, at=now, verifier=FakeVerifier(_principal(now)))
    assert result["authorization_status"] == "OFFLINE_VERIFIER_ACCEPTED"
    assert result["external_identity_verified"] is False
    assert result["safe_to_trade"] is False
    assert result["notification_dispatch_allowed"] is False
