"""Validate cryptographic consistency of an offline incident digest.

The SHA-256 fingerprint is an integrity checksum, NOT an authentication
signature or evidence of an authoritative upstream incident source.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Mapping
from typing import Any

_INCIDENT = re.compile(r"[A-Z0-9_]{1,100}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")


def validate_offline_digest(report: Mapping[str, Any]) -> bool:
    incidents = report.get("incidents")
    if not isinstance(incidents, list) or not incidents:
        return False
    if not all(isinstance(i, str) and _INCIDENT.fullmatch(i) for i in incidents):
        return False
    if incidents != sorted(set(incidents)):
        return False
    claimed = report.get("dedup_sha256")
    if not isinstance(claimed, str) or _HASH.fullmatch(claimed) is None:
        return False
    expected = hashlib.sha256(
        json.dumps(incidents, sort_keys=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()
    return (
        report.get("schema") == "sidedeck.sd152.offline-alert-digest/1"
        and report.get("severity") == "ACTION_REQUIRED"
        and report.get("operator_action") == "MANUAL_REVIEW_ONLY"
        and report.get("delivery_status") == "NOT_CONFIGURED"
        and report.get("execution_release") == "ETORO_DEMO_NOT_RELEASED"
        and report.get("safe_to_trade") is False
        and report.get("clear_halt_allowed") is False
        and hmac.compare_digest(expected, claimed)
    )
