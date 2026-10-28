"""Read-only local operator escalation assessment; never sends notifications."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def assess_offline_watchdog(
    digest: Mapping[str, Any],
    journal_record: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Fail closed on missing journal evidence or an undelivered critical incident.

    Repeated local observations are not evidence of external notification.
    This verdict grants no broker, recovery, or delivery permissions.
    """
    valid_digest = (
        digest.get("schema") == "sidedeck.sd152.offline-alert-digest/1"
        and digest.get("execution_release") == "ETORO_DEMO_NOT_RELEASED"
        and digest.get("safe_to_trade") is False
        and digest.get("clear_halt_allowed") is False
        and digest.get("delivery_status") == "NOT_CONFIGURED"
        and digest.get("severity") in {"ACTION_REQUIRED", "INFORMATIONAL"}
        and isinstance(digest.get("incidents"), list)
        and isinstance(digest.get("dedup_sha256"), str)
    )
    record = journal_record if isinstance(journal_record, Mapping) else {}
    valid_record = (
        record.get("schema") == "sidedeck.sd152.offline-alert-record/1"
        and record.get("execution_release") == "ETORO_DEMO_NOT_RELEASED"
        and record.get("safe_to_trade") is False
        and record.get("clear_halt_allowed") is False
        and record.get("delivery_status") == "NOT_CONFIGURED"
        and type(record.get("observations")) is int
        and record["observations"] >= 1
    )
    if not valid_digest or not valid_record:
        incidents = ["WATCHDOG_EVIDENCE_INVALID"]
    elif digest["severity"] == "ACTION_REQUIRED":
        incidents = ["OPERATOR_ACKNOWLEDGEMENT_AND_DELIVERY_NOT_CONFIGURED"]
    else:
        incidents = []
    return {
        "schema": "sidedeck.sd152.offline-watchdog/1",
        "status": "ESCALATION_REQUIRED" if incidents else "OBSERVATION_ONLY",
        "incidents": incidents,
        "delivery_status": "NOT_CONFIGURED",
        "external_notification_confirmed": False,
        "safe_to_trade": False,
        "clear_halt_allowed": False,
        "execution_release": "ETORO_DEMO_NOT_RELEASED",
    }
