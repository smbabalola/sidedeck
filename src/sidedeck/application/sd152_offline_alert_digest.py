"""Deterministic, read-only alert digest for the offline SideDeck operator UI.

No alert delivery, broker transport, database writes or release authority.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any


def build_offline_alert_digest(alerts: Mapping[str, Any]) -> dict[str, Any]:
    """Return a stable, safe-to-display digest; reject untrusted report shapes."""
    valid = (
        alerts.get("schema") == "sidedeck.sd152.offline-operator-alerts/1"
        and alerts.get("execution_release") == "ETORO_DEMO_NOT_RELEASED"
        and alerts.get("safe_to_trade") is False
        and alerts.get("automatic_recovery_allowed") is False
        and alerts.get("clear_halt_allowed") is False
        and alerts.get("status") in {"OBSERVATION_ONLY", "ATTENTION_REQUIRED"}
        and isinstance(alerts.get("incidents"), list)
        and all(isinstance(x, str) and x.isupper()
                and len(x) <= 100 and all(c.isupper() or c.isdigit() or c == "_"
                                         for c in x)
                for x in alerts.get("incidents", []))
    )
    if not valid or (alerts["status"] == "OBSERVATION_ONLY") != (not alerts["incidents"]):
        incidents = ["OPERATOR_ALERT_REPORT_INVALID"]
    else:
        incidents = sorted(set(alerts["incidents"]))
    canonical = json.dumps(incidents, sort_keys=True, separators=(",", ":"))
    return {
        "schema": "sidedeck.sd152.offline-alert-digest/1",
        "severity": "ACTION_REQUIRED" if incidents else "INFORMATIONAL",
        "incidents": incidents,
        "dedup_sha256": hashlib.sha256(canonical.encode("ascii")).hexdigest(),
        "operator_action": "MANUAL_REVIEW_ONLY" if incidents else "NONE",
        "delivery_status": "NOT_CONFIGURED",
        "safe_to_trade": False,
        "clear_halt_allowed": False,
        "execution_release": "ETORO_DEMO_NOT_RELEASED",
    }
