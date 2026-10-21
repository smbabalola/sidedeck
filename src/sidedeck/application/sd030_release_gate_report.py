"""Sanitized paper-release gate report; never grants execution authority."""
from __future__ import annotations

from typing import Any

from sidedeck.application.sd036_etoro_demo_desk import etoro_demo_status


def build_release_gate_report(paper_audit: dict[str, Any], rehearsal: dict[str, Any]) -> dict[str, Any]:
    if paper_audit.get("overall_status") != "NO_GO" or paper_audit.get("release_enabled") is not False:
        raise ValueError("paper readiness must remain an explicit NO_GO")
    if rehearsal.get("status") != "REHEARSED" or rehearsal.get("broker_execution") != "DISABLED":
        raise ValueError("rehearsal evidence is not safely bounded")
    checks = paper_audit.get("checks")
    if not isinstance(checks, list):
        raise ValueError("paper readiness checks are required")
    return {
        "schema_version": 1,
        "gate": "PAPER_RELEASE",
        "overall_status": "NO_GO",
        "engineering_rehearsal": "PASS",
        "release_enabled": False,
        "paper_order_submission": "DISABLED",
        "human_approval": "REQUIRED_SEPARATE_OWNER_RELEASE",
        "account_mapping": "UNVERIFIED",
        "broker_reconciliation": "UNRELEASED",
        "kill_switch": "UNRELEASED",
        "protected_baseline": "PRESERVED",
        "etoro_demo": etoro_demo_status(),
        "blocking_controls": sorted(str(check.get("name")) for check in checks if isinstance(check, dict) and check.get("status") == "FAIL"),
        "rehearsal": {
            "status": "REHEARSED",
            "final_state": rehearsal.get("final_state"),
            "event_count": rehearsal.get("event_count"),
            "broker_execution": "DISABLED",
        },
        "owner_action": "No approval is requested by this report; a separate bounded release decision is required before any paper-order work.",
    }
