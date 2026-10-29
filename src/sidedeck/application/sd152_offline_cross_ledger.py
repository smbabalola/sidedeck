"""Offline recovery evidence aggregation, deliberately never an execution gate.

All inputs are independently prepared, read-only reports. A local report cannot
prove the authentic broker account, immutable remote anchors or owner approval.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def summarize_recovery_evidence(
    fence: Mapping[str, Any], manifest: Mapping[str, Any] | None,
) -> dict[str, Any]:
    reasons: list[str] = []
    if (fence.get("schema") != "sidedeck.sd152.operator-status/1"
            or fence.get("execution_release") != "ETORO_DEMO_NOT_RELEASED"
            or fence.get("safe_to_trade") is not False
            or fence.get("clear_halt_allowed") is not False):
        reasons.append("FENCE_EVIDENCE_INVALID")
    if fence.get("fence_state") != "IDLE":
        reasons.append("WORKER_FENCE_NOT_IDLE")
    if manifest is None:
        reasons.append("RECOVERY_MANIFEST_UNAVAILABLE")
    else:
        if manifest.get("schema") != "sidedeck.sd153.offline-recovery-evidence/1":
            reasons.append("RECOVERY_MANIFEST_INVALID")
        if manifest.get("evidence_origin") != "LOCAL_OFFLINE_FIXTURE_ONLY":
            reasons.append("RECOVERY_MANIFEST_ORIGIN_INVALID")
        if manifest.get("execution_release") != "ETORO_DEMO_NOT_RELEASED":
            reasons.append("RECOVERY_MANIFEST_RELEASE_INVALID")
        if manifest.get("owner_signature") != "NOT_PROVIDED":
            reasons.append("RECOVERY_MANIFEST_AUTHORITY_UNVERIFIED")
        if manifest.get("status") != "NO_RECOVERY_READS_NEEDED":
            reasons.append("RECOVERY_MANIFEST_REQUIRES_REVIEW")
        if manifest.get("broker_account_verified") is not False:
            reasons.append("BROKER_VERIFICATION_CLAIM_INVALID")
        if not isinstance(manifest.get("manifest_sha256"), str) or len(manifest["manifest_sha256"]) != 64:
            reasons.append("RECOVERY_MANIFEST_DIGEST_INVALID")
        if not isinstance(manifest.get("errors"), list) or manifest["errors"]:
            reasons.append("RECOVERY_MANIFEST_ERRORS")
    # Absence of local inconsistencies is not broker-backed recovery evidence.
    reasons.extend(["INDEPENDENT_REMOTE_ANCHOR_UNVERIFIED", "BROKER_ACCOUNT_UNVERIFIED"])
    return {
        "schema": "sidedeck.sd152.offline-cross-ledger-review/1",
        "status": "MANUAL_REVIEW_REQUIRED",
        "reasons": sorted(set(reasons)),
        "safe_to_trade": False,
        "automatic_get_allowed": False,
        "automatic_post_allowed": False,
        "clear_halt_allowed": False,
        "execution_release": "ETORO_DEMO_NOT_RELEASED",
    }
