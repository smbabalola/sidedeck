"""Offline paper-release safety audit; never connects to a broker.

The audit deliberately distinguishes a consistent synthetic read-only snapshot
from a releasable paper-order control plane.  A green individual check cannot
enable paper orders.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SafetyCheck:
    name: str
    status: str
    evidence: str
    residual: str


def audit_paper_release_controls() -> dict[str, Any]:
    checks = (
        SafetyCheck("broker_isolation", "PASS", "Alpaca binding is exact-host and disabled", "No broker request is permitted by this audit"),
        SafetyCheck("order_submission_disabled", "PASS", "submit_order raises PermissionError", "No paper or real order capability"),
        SafetyCheck("proposal_vs_order_boundary", "PASS", "TradeIntent and proposal audit are non-executing", "No approved order object/release path"),
        SafetyCheck("idempotency", "PARTIAL", "proposal audit has scoped idempotency", "Paper order/fill idempotency lifecycle is not released"),
        SafetyCheck("stale_quote_guard", "PASS", "MarketSnapshot and risk screen reject stale/future data", "No broker-side quote freshness evidence"),
        SafetyCheck("duplicate_orders", "FAIL", "No released paper order dispatcher exists", "Duplicate submission protection is not independently evidenced"),
        SafetyCheck("partial_fills_reconciliation", "FAIL", "Accounting supports deterministic local events only", "Broker ack/fill/position reconciliation is not released"),
        SafetyCheck("approval_signature", "FAIL", "No independently verified owner approval record", "Human approval and signing workflow required"),
        SafetyCheck("kill_switch", "FAIL", "No released broker kill-switch control", "Emergency stop must be independently tested"),
        SafetyCheck("account_separation", "FAIL", "Credential names do not prove distinct accounts", "Account mapping and dedicated paper account proof required"),
        SafetyCheck("protected_baseline", "PASS", "Existing eToro baseline is unattributed and protected", "No SideDeck close/modify path"),
    )
    return {
        "schema_version": 1,
        "overall_status": "NO_GO",
        "release_enabled": False,
        "paper_order_submission": "DISABLED",
        "checks": [{"name": check.name, "status": check.status, "evidence": check.evidence, "residual": check.residual} for check in checks],
        "blocking_checks": [check.name for check in checks if check.status == "FAIL"],
        "owner_approval_required": True,
        "broker_execution": "DISABLED",
    }
