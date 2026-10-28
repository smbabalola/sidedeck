"""SD-152 offline-only operator alert assessment.

Pure evaluation of *already prepared* diagnostic reports. No broker, secrets,
SQLite mutation, release authority, network, or automatic recovery.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

SEVERE = frozenset({
    "STALE_RUNNING_HEARTBEAT_RECONCILIATION_REQUIRED",
    "MANUAL_RECONCILIATION_REQUIRED_NO_AUTOMATIC_TAKEOVER",
    "HEARTBEAT_CLOCK_UNVERIFIED",
})


def evaluate_offline_alerts(
    fence_health: Mapping[str, Any],
    recovery_dossier: Mapping[str, Any],
) -> dict[str, Any]:
    """Produce deterministic, fail-closed read-only operator status.

    A positive verdict here never authorises trading; this is an alert feed.
    Unknown or malformed evidence is an incident, not an empty/healthy state.
    """
    incidents: list[str] = []
    if fence_health.get("schema") != "sidedeck.sd152.offline-fence-health/1":
        incidents.append("FENCE_EVIDENCE_INVALID")
    if fence_health.get("execution_release") != "ETORO_DEMO_NOT_RELEASED":
        incidents.append("RELEASE_STATE_UNVERIFIED")
    if fence_health.get("broker_route") != "SIMULATED_LOCAL":
        incidents.append("BROKER_ROUTE_UNVERIFIED")
    state = fence_health.get("state")
    if state not in ("IDLE", "RUNNING", "UNRESOLVED"):
        incidents.append("FENCE_STATE_INVALID")
    elif state == "UNRESOLVED":
        incidents.append("FENCE_UNRESOLVED")
    elif state == "RUNNING":
        incidents.append("WORKER_ACTIVE_REQUIRES_OBSERVATION")
    alerts = fence_health.get("alerts")
    if not isinstance(alerts, list) or not all(isinstance(x, str) for x in alerts):
        incidents.append("FENCE_ALERTS_INVALID")
    else:
        incidents.extend(x for x in alerts if x in SEVERE)
        if any(x not in SEVERE | {"EXCLUSIVE_WORKER_ACTIVE"} for x in alerts):
            incidents.append("UNKNOWN_FENCE_ALERT")
    if not isinstance(recovery_dossier.get("uncertain_orders"), list):
        incidents.append("RECOVERY_EVIDENCE_INVALID")
    elif recovery_dossier["uncertain_orders"]:
        incidents.append("UNCERTAIN_ORDER_REQUIRES_MANUAL_RECONCILIATION")
    if recovery_dossier.get("execution_release") != "ETORO_DEMO_NOT_RELEASED":
        incidents.append("RECOVERY_RELEASE_UNVERIFIED")
    ordered = sorted(set(incidents))
    return {
        "schema": "sidedeck.sd152.offline-operator-alerts/1",
        "status": "ATTENTION_REQUIRED" if ordered else "OBSERVATION_ONLY",
        "incidents": ordered,
        "safe_to_trade": False,
        "automatic_recovery_allowed": False,
        "clear_halt_allowed": False,
        "execution_release": "ETORO_DEMO_NOT_RELEASED",
    }
