"""Research acceptance decisions are independent of CI success and paper-order permissions."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResearchEvidence:
    sec_metrics_validated: int
    sec_metrics_expected: int
    price_history_corrob: bool
    corporate_actions_verified: bool
    valuation_basis_verified: bool
    agents_executed: bool
    independent_results_accepted: bool
    cost_cap_authorized: bool


def readiness_report(evidence: ResearchEvidence) -> dict[str, object]:
    if evidence.sec_metrics_expected <= 0 or not 0 <= evidence.sec_metrics_validated <= evidence.sec_metrics_expected:
        raise ValueError("invalid metric counts")
    blocks: list[str] = []
    if evidence.sec_metrics_validated != evidence.sec_metrics_expected:
        blocks.append("FINANCIAL_COVERAGE_INCOMPLETE")
    if not evidence.price_history_corrob:
        blocks.append("HISTORICAL_CLOSE_UNCORROBORATED")
    if not evidence.corporate_actions_verified:
        blocks.append("CORPORATE_ACTIONS_UNVERIFIED")
    if not evidence.valuation_basis_verified:
        blocks.append("PRICE_SHARE_EPS_BASIS_UNVERIFIED")
    if not evidence.cost_cap_authorized:
        blocks.append("MODEL_SPEND_NOT_AUTHORIZED")
    if not evidence.agents_executed:
        blocks.append("REAL_AGENT_RUNS_NOT_PERFORMED")
    if not evidence.independent_results_accepted:
        blocks.append("PAIRED_AGENT_RESULTS_NOT_ACCEPTED")
    return {
        "m2_research_acceptance": "NO_GO" if blocks else "EVIDENCE_READY_FOR_REVIEW",
        "blockers": blocks,
        "execution_enabled": False,
        "broker_execution": "DISABLED",
        "paper_order_release": "NO_GO",
    }
