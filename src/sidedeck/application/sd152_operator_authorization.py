"""Fail-closed local operator authorization *assessment*, without an identity provider.

An actor name or an acknowledgement row never proves a verified principal.
This module makes no grants and cannot authorize trading, incident resolution or
notification dispatch. External identity integration remains a separate gate.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def assess_operator_ack_authorization(
    acknowledgement: Mapping[str, Any] | None,
    identity_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Refuse to upgrade an unverified local identity to an authenticated operator."""
    ack = acknowledgement if isinstance(acknowledgement, Mapping) else {}
    valid_ack = (
        ack.get("schema") == "sidedeck.sd152.offline-operator-ack/1"
        and ack.get("execution_release") == "ETORO_DEMO_NOT_RELEASED"
        and ack.get("safe_to_trade") is False
        and ack.get("clear_halt_allowed") is False
        and ack.get("incident_resolved") is False
        and ack.get("external_notification_confirmed") is False
        and ack.get("delivery_status") == "NOT_CONFIGURED"
    )
    # No external issuer, signature verification or authenticated session exists.
    # Caller-provided identity objects are never sufficient proof of authority.
    evidence_present = identity_evidence is not None
    incidents = [] if valid_ack else ["OPERATOR_ACKNOWLEDGEMENT_INVALID"]
    if evidence_present:
        incidents.append("OPERATOR_IDENTITY_EVIDENCE_UNTRUSTED")
    incidents.append("OPERATOR_AUTHENTICATION_NOT_CONFIGURED")
    return {
        "schema": "sidedeck.sd152.operator-ack-authorization/1",
        "authorization_status": "DENIED",
        "incidents": sorted(set(incidents)),
        "operator_identity_verified": False,
        "acknowledgement_authorized": False,
        "notification_dispatch_allowed": False,
        "incident_resolved": False,
        "safe_to_trade": False,
        "clear_halt_allowed": False,
        "execution_release": "ETORO_DEMO_NOT_RELEASED",
    }
