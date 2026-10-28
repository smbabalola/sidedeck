"""Offline operator incident-scope authorization policy.

A verified-principal *shape* is not proof of a verified identity. The only
entry point here accepts a trusted verifier as a dependency, defaulting to a
disabled verifier. No browser-provided principal or bypass flag is accepted.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from sidedeck.application.sd152_operator_identity_boundary import (
    DisabledOperatorIdentityVerifier, OperatorAuthenticationDenied,
    OperatorIdentityVerifier,
)

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def authorize_operator_incident(
    token: str, *, audience: str, tenant: str, incident_digest: str,
    at: datetime, verifier: OperatorIdentityVerifier | None = None,
) -> dict[str, Any]:
    """Check trusted subject, tenant, role, expiry; never authorize trading."""
    if (not isinstance(at, datetime) or at.tzinfo is None or at.utcoffset() is None
            or not isinstance(token, str) or not isinstance(audience, str)
            or not audience or not isinstance(tenant, str) or not tenant
            or not isinstance(incident_digest, str)
            or _DIGEST.fullmatch(incident_digest) is None):
        raise OperatorAuthenticationDenied("invalid operator authorization request")
    actual_verifier = verifier if verifier is not None else DisabledOperatorIdentityVerifier()
    principal = actual_verifier.verify(token, audience=audience, at=at)
    if (not principal.subject or not principal.issuer
            or principal.tenant != tenant
            or "incident:acknowledge" not in principal.roles
            or principal.expires_at.tzinfo is None
            or principal.expires_at.astimezone(UTC) <= at.astimezone(UTC)):
        raise OperatorAuthenticationDenied("operator is not authorized for this incident")
    return {
        "schema": "sidedeck.sd152.operator-incident-authorization/1",
        "incident_digest": incident_digest,
        "subject": principal.subject,
        "tenant": tenant,
        "identity_issuer": principal.issuer,
        "authorization_status": "OFFLINE_VERIFIER_ACCEPTED",
        "external_identity_verified": False,
        "notification_dispatch_allowed": False,
        "safe_to_trade": False,
        "clear_halt_allowed": False,
        "execution_release": "ETORO_DEMO_NOT_RELEASED",
    }
