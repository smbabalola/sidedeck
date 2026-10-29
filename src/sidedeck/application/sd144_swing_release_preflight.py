"""SD-144 release preflight for a single SWING strategy, without self-admission.

Reports precisely which independently evidenced conditions prevent strategy-driven
execution. Does not construct StrategyAdmission, grant permission or place orders.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sidedeck.application.sd071_decision_engine import MIN_OOS_TRADES_FLOOR


def swing_strategy_release_preflight(
    evidence: Mapping[str, Any] | None,
    *,
    market_data_rights_verified: bool = False,
    broker_execution_price_verified: bool = False,
    independent_admission_verified: bool = False,
) -> dict[str, Any]:
    facts = evidence if isinstance(evidence, Mapping) else {}
    gaps: list[str] = []
    if not facts:
        gaps.append("STRATEGY_EVIDENCE_MISSING")
    if facts.get("track") != "SWING":
        gaps.append("SWING_TRACK_NOT_VERIFIED")
    if facts.get("source") != "GENUINE_HISTORICAL":
        gaps.append("GENUINE_HISTORICAL_DATA_NOT_VERIFIED")
    if facts.get("locked_oos") is not True:
        gaps.append("LOCKED_OUT_OF_SAMPLE_NOT_VERIFIED")
    trades = facts.get("qualified_oos_trades")
    if type(trades) is not int or trades < MIN_OOS_TRADES_FLOOR:
        gaps.append("QUALIFIED_OOS_TRADES_BELOW_FLOOR")
    if facts.get("reproducible_evidence_ref") in (None, ""):
        gaps.append("REPRODUCIBLE_EVIDENCE_MISSING")
    if not market_data_rights_verified:
        gaps.append("MARKET_DATA_RIGHTS_UNVERIFIED")
    if not broker_execution_price_verified:
        gaps.append("BROKER_EXECUTION_PRICE_UNVERIFIED")
    if not independent_admission_verified:
        gaps.append("INDEPENDENT_STRATEGY_ADMISSION_UNVERIFIED")
    return {
        "schema": "sidedeck.sd144.swing-strategy-release-preflight/1",
        "status": "BLOCKED_EXTERNAL" if gaps else "READY_FOR_SEPARATE_RELEASE_REVIEW",
        "missing_evidence": sorted(gaps),
        "qualified_oos_floor": MIN_OOS_TRADES_FLOOR,
        "strategy_admitted_by_this_report": False,
        "safe_to_trade": False,
        "broker_execution_allowed": False,
        "execution_release": "ETORO_DEMO_NOT_RELEASED",
    }
