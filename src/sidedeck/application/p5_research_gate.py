"""Research-only AI agent decisions routed through SideDeck's existing proposal gate."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from sidedeck.application.ai_agents import AgentResult, normalize_intent
from sidedeck.application.proposals import evaluate_proposal
from sidedeck.domain.contracts import ExperimentManifest, MarketSnapshot, TradeIntent


@dataclass(frozen=True)
class ResearchDecision:
    source: str
    portfolio_id: str
    outcome: str
    reason: str
    intent: TradeIntent | None


def assess_agent_research(
    result: AgentResult,
    manifest: ExperimentManifest,
    snapshot: MarketSnapshot,
    *,
    strategy_id: str,
    decision_timestamp: datetime,
    proposed_shares: Decimal | None = None,
    max_market_age: timedelta = timedelta(minutes=2),
) -> ResearchDecision:
    """An accepted output is a proposal only; no portfolio or broker calls."""
    if result.ticker != snapshot.ticker:
        return ResearchDecision(result.upstream, result.portfolio_id, "REJECTED",
                                "market_snapshot_ticker_mismatch", None)
    try:
        intent = normalize_intent(
            result, experiment_id=manifest.experiment_id,
            strategy_id=strategy_id,
            market_timestamp=snapshot.market_timestamp,
            decision_timestamp=decision_timestamp,
            proposed_shares=proposed_shares,
        )
        decision = evaluate_proposal(intent, manifest, snapshot, max_market_age=max_market_age)
    except (ValueError, KeyError):
        return ResearchDecision(result.upstream, result.portfolio_id, "REJECTED",
                                "malformed_or_unsized_agent_decision", None)
    return ResearchDecision(result.upstream, result.portfolio_id,
                            "PROPOSAL_ACCEPTED" if decision.accepted else "REJECTED",
                            decision.reason, decision.intent if decision.accepted else None)
