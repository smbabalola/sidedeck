"""Offline notification delivery-readiness assessment. No sender or retry dispatcher.

Only explicitly local evidence is admitted. A provider response can never be
claimed through caller-supplied text because no authenticated provider exists.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def assess_offline_delivery_attempt(
    outbox: Mapping[str, Any],
    *,
    provider_configured: bool = False,
    operator_authorized: bool = False,
) -> dict[str, Any]:
    """Describe an attempt blocked before dispatch, never create or send it."""
    valid = (
        outbox.get("schema") == "sidedeck.sd152.offline-notification-outbox/1"
        and outbox.get("delivery_status") == "NOT_CONFIGURED"
        and outbox.get("external_notification_confirmed") is False
        and outbox.get("dispatch_allowed") is False
        and outbox.get("safe_to_trade") is False
        and outbox.get("clear_halt_allowed") is False
        and outbox.get("execution_release") == "ETORO_DEMO_NOT_RELEASED"
        and type(outbox.get("observations")) is int
        and outbox["observations"] >= 1
    )
    reasons = [] if valid else ["OUTBOX_EVIDENCE_INVALID"]
    if provider_configured or operator_authorized:
        reasons.append("UNVERIFIED_PROVIDER_OR_OPERATOR_CLAIM")
    reasons.append("EXTERNAL_DELIVERY_NOT_CONFIGURED")
    return {
        "schema": "sidedeck.sd152.offline-notification-attempt/1",
        "attempt_status": "BLOCKED_BEFORE_DISPATCH",
        "reasons": sorted(set(reasons)),
        "provider_attempted": False,
        "provider_receipt_verified": False,
        "delivery_status": "NOT_CONFIGURED",
        "retry_dispatch_allowed": False,
        "operator_authorized": False,
        "safe_to_trade": False,
        "clear_halt_allowed": False,
        "execution_release": "ETORO_DEMO_NOT_RELEASED",
    }
