"""Translate SD-112 pooled research output to a non-executable SWING release review.

A pooled proposal is research-only even if its internal verdict is positive.
Never promote its OOS counts to per-instrument SD-071 admission.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sidedeck.application.sd112_pooled_admission import SCHEMA as POOLED_SCHEMA


def audit_pooled_swing_candidate(report: Mapping[str, Any], strategy: str) -> dict[str, Any]:
    reasons: list[str] = []
    if (report.get("schema") != POOLED_SCHEMA
            or report.get("status") != "PROPOSAL_ONLY"
            or report.get("production_admission_gate") !=
            "UNCHANGED (SD-022 + SD-071 per instrument)"):
        reasons.append("POOLED_RESEARCH_REPORT_INVALID")
    candidates = report.get("strategies")
    if not isinstance(candidates, list):
        candidates = []
        reasons.append("STRATEGY_CANDIDATES_MISSING")
    matched = [x for x in candidates if isinstance(x, Mapping)
               and x.get("strategy") == strategy]
    if len(matched) != 1:
        reasons.append("STRATEGY_NOT_UNIQUELY_IDENTIFIED")
    else:
        selected = matched[0]
        if selected.get("verdict") != "PROPOSED_FOR_OWNER_REVIEW":
            reasons.append("POOLED_STRATEGY_NOT_PROPOSED")
        holdout = selected.get("holdout")
        if not isinstance(holdout, Mapping) or holdout.get("status") != "SEALED":
            reasons.append("SEALED_HOLDOUT_NOT_VERIFIED")
    reasons.extend([
        "POOLED_EVIDENCE_NOT_PER_INSTRUMENT_ADMISSION",
        "INDEPENDENT_STRATEGY_ADMISSION_UNVERIFIED",
        "BROKER_EXECUTION_PRICE_UNVERIFIED",
    ])
    return {
        "schema": "sidedeck.sd144.pooled-swing-audit/1",
        "strategy": strategy,
        "status": "BLOCKED_EXTERNAL",
        "reasons": sorted(set(reasons)),
        "production_admission_unchanged": True,
        "execution_release": "ETORO_DEMO_NOT_RELEASED",
        "safe_to_trade": False,
        "broker_execution_allowed": False,
    }
