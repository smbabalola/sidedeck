"""Local-only incident presentation combining alert, journal and optional acknowledgement."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sidedeck.application.sd152_offline_watchdog import assess_offline_watchdog


def report_offline_incident(
    digest: Mapping[str, Any], journal_record: Mapping[str, Any] | None,
    acknowledgement: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """An acknowledgement is not a delivery receipt, incident resolution or trading grant."""
    watchdog = assess_offline_watchdog(digest, journal_record)
    ack = acknowledgement if isinstance(acknowledgement, Mapping) else {}
    present = acknowledgement is not None
    valid = (
        ack.get("schema") == "sidedeck.sd152.offline-operator-ack/1"
        and ack.get("digest") == digest.get("dedup_sha256")
        and isinstance(ack.get("actor"), str) and bool(ack["actor"])
        and isinstance(ack.get("acknowledged_at"), str) and bool(ack["acknowledged_at"])
        and ack.get("delivery_status") == "NOT_CONFIGURED"
        and ack.get("external_notification_confirmed") is False
        and ack.get("incident_resolved") is False
        and ack.get("safe_to_trade") is False
        and ack.get("clear_halt_allowed") is False
        and ack.get("execution_release") == "ETORO_DEMO_NOT_RELEASED"
        and watchdog["status"] == "ESCALATION_REQUIRED"
        and watchdog["incidents"] != ["WATCHDOG_EVIDENCE_INVALID"]
    )
    issues = list(watchdog["incidents"])
    if present and not valid:
        issues.append("OPERATOR_ACKNOWLEDGEMENT_INVALID")
    return {
        "schema": "sidedeck.sd152.offline-incident-report/1",
        "status": "ESCALATION_REQUIRED" if issues else "OBSERVATION_ONLY",
        "incidents": sorted(set(issues)),
        "operator_acknowledged": bool(present and valid),
        "incident_resolved": False,
        "external_notification_confirmed": False,
        "delivery_status": "NOT_CONFIGURED",
        "safe_to_trade": False,
        "clear_halt_allowed": False,
        "execution_release": "ETORO_DEMO_NOT_RELEASED",
    }
