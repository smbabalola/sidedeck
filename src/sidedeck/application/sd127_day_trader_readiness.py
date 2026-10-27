"""SD-127: strictly read-only Day Trader engineering readiness for the workstation.

This is code-derived readiness, NOT a live account/credential/permission check.
Never open .env, order transports, data providers, databases or trading sessions.
"""
from __future__ import annotations

from typing import Any

from sidedeck.application.sd107_demo_gateway import BROKER_ROUTES
from sidedeck.application.sd123_day_demo_integration import release_status


def day_trader_readiness() -> dict[str, Any]:
    """Truthful static capability gates; production admission is never inferred."""
    limits = release_status()
    route = BROKER_ROUTES.get("ETORO_DEMO", "UNAVAILABLE")
    if (limits["broker_route"] != "ETORO_DEMO_NOT_RELEASED"
            or route != "NOT_RELEASED"):
        # A code change that permits release must not silently upgrade this
        # read-only API into claiming operational trading readiness.
        raise ValueError("Day Trader release state differs from reviewed offline contract")
    return {
        "schema_version": 1,
        "module": "DAY_TRADER",
        "source": "CODE_DERIVED_OFFLINE",
        "execution_enabled": False,
        "broker_execution": "DISABLED",
        "real_execution": "PERMANENTLY_EXCLUDED",
        "data_status": limits["data_admission"],
        "strategy_status": limits["strategy_admission"],
        "demo_release": route,
        "gates": [
            {
                "id": "research",
                "label": "Day Trader research workstation",
                "status": "IMPLEMENTED_OFFLINE",
                "detail": "Saved fixture research, scans and labelled scenarios; not market evidence.",
                "next_action": "Review local research and import genuine licensed five-minute history.",
            },
            {
                "id": "market_data",
                "label": "Genuine five-minute data",
                "status": "BLOCKED_EXTERNAL",
                "detail": "eToro-shaped samples are unverified midpoint research inputs.",
                "next_action": "Separately authorise bounded eToro data discovery and validate source rights, coverage and quality.",
            },
            {
                "id": "strategy",
                "label": "Independent DAY strategy qualification",
                "status": "BLOCKED_EXTERNAL",
                "detail": "A chart signal, fixture pass or skill score cannot independently admit a strategy.",
                "next_action": "Run locked out-of-sample validation on accepted real five-minute history.",
            },
            {
                "id": "offline_cycle",
                "label": "Simulated DAY entry and session exit",
                "status": "IMPLEMENTED_OFFLINE",
                "detail": "Signed-policy fixture tests cover simulated fills, daily flatten, restart and risk refusal.",
                "next_action": "Keep synthetic execution distinct from broker evidence.",
            },
            {
                "id": "broker",
                "label": "Autonomous eToro Demo execution",
                "status": "NOT_RELEASED",
                "detail": "Live Demo order transport is locked. This endpoint cannot read account state or enable it.",
                "next_action": "Complete real Demo adapter review, external audit anchors and a bounded owner-signed release.",
            },
        ],
        "limitations": [
            "The latest saved Day Trader run is local research, not a live feed.",
            "Account portfolio state and the four protected holdings are not read by this endpoint.",
            "A green test suite does not authorise an eToro Demo order.",
        ],
    }
