"""Read-only SD-152 status contract; no broker or recovery control surfaces."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sidedeck.application.sd152_offline_alert_digest import build_offline_alert_digest
from sidedeck.application.sd152_offline_operator_alerts import offline_operator_snapshot


def operator_status_document(service: Any, *, now: Any) -> dict[str, Any]:
    """Build a defensive, explicitly offline operator status document.

    The caller is responsible for keeping this behind a read-only local
    diagnostics endpoint. This method never starts or advances any runner.
    """
    alerts = offline_operator_snapshot(service, now=now)
    digest = build_offline_alert_digest(alerts)
    return {
        "schema": "sidedeck.sd152.operator-status/1",
        "source": "LOCAL_OFFLINE_DIAGNOSTICS_ONLY",
        "status": digest["severity"],
        "incidents": digest["incidents"],
        "incident_digest_sha256": digest["dedup_sha256"],
        "delivery_status": "NOT_CONFIGURED",
        "recovery": "SEPARATELY_AUTHORISED_MANUAL_REVIEW_ONLY",
        "broker_account_verified": False,
        "safe_to_trade": False,
        "automatic_get_allowed": False,
        "automatic_post_allowed": False,
        "clear_halt_allowed": False,
        "execution_release": "ETORO_DEMO_NOT_RELEASED",
    }


def is_safe_operator_status_document(value: Mapping[str, Any]) -> bool:
    """Validate a local display document without granting authority."""
    return (
        value.get("schema") == "sidedeck.sd152.operator-status/1"
        and value.get("source") == "LOCAL_OFFLINE_DIAGNOSTICS_ONLY"
        and value.get("status") in ("ACTION_REQUIRED", "INFORMATIONAL")
        and isinstance(value.get("incidents"), list)
        and all(isinstance(x, str) for x in value["incidents"])
        and value.get("delivery_status") == "NOT_CONFIGURED"
        and value.get("recovery") == "SEPARATELY_AUTHORISED_MANUAL_REVIEW_ONLY"
        and value.get("broker_account_verified") is False
        and value.get("safe_to_trade") is False
        and value.get("automatic_get_allowed") is False
        and value.get("automatic_post_allowed") is False
        and value.get("clear_halt_allowed") is False
        and value.get("execution_release") == "ETORO_DEMO_NOT_RELEASED"
    )
