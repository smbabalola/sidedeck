"""No local token or client-owned role can verify an operator."""
from datetime import UTC, datetime

import pytest

from sidedeck.application.sd152_operator_identity_boundary import (
    DisabledOperatorIdentityVerifier, OperatorAuthenticationDenied,
)


@pytest.mark.parametrize("token", [
    "", "operator", "Bearer abc",
    '{"role":"admin","verified":true,"issuer":"self"}',
])
def test_disabled_identity_provider_rejects_all_claims(token):
    verifier = DisabledOperatorIdentityVerifier()
    assert verifier.identity_provider_configured is False
    with pytest.raises(OperatorAuthenticationDenied):
        verifier.verify(token, audience="sidedeck-operator", at=datetime.now(UTC))
