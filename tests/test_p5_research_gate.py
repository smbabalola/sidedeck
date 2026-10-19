from datetime import datetime, timezone
from decimal import Decimal

from sidedeck.application.ai_agents import AgentResult
from sidedeck.application.p5_research_gate import assess_agent_research
from sidedeck.domain.contracts import (
    ExperimentManifest, MarketSnapshot, PriceType, Session,
)


NOW = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)


def manifest():
    return ExperimentManifest(
        experiment_id="research-match", configuration_revision="p5",
        created_at=NOW, instruments=("US:SOFI",),
        data_policy="synthetic-unit-only",
    )


def quote():
    return MarketSnapshot(
        instrument_id="US:SOFI", ticker="SOFI",
        provider="synthetic-unit-test", price_type=PriceType.QUOTE,
        price=Decimal("40"), market_timestamp=NOW,
        ingestion_timestamp=NOW, session=Session.REGULAR, quality="synthetic",
    )


def test_hold_is_accepted_as_proposal_only():
    result = AgentResult("TradingAgents", "revision", "tradingagents",
                         "SOFI", "HOLD", "Wait for confirmation", "")
    decision = assess_agent_research(
        result, manifest(), quote(), strategy_id="team-a", decision_timestamp=NOW,
    )
    assert decision.outcome == "PROPOSAL_ACCEPTED"
    assert decision.intent is not None
    assert decision.intent.portfolio_id == "tradingagents"
    assert decision.intent.quantity is None


def test_buy_without_explicit_sizing_is_rejected():
    result = AgentResult("AI Hedge Fund", "revision", "ai-trading",
                         "SOFI", "BUY", "Bullish research", "")
    decision = assess_agent_research(
        result, manifest(), quote(), strategy_id="team-b", decision_timestamp=NOW,
    )
    assert decision.outcome == "REJECTED"
    assert decision.intent is None


def test_agent_cannot_take_other_ticker_snapshot():
    result = AgentResult("TradingAgents", "revision", "tradingagents",
                         "AAPL", "HOLD", "Wait", "")
    decision = assess_agent_research(
        result, manifest(), quote(), strategy_id="team-a", decision_timestamp=NOW,
    )
    assert decision.reason == "market_snapshot_ticker_mismatch"
