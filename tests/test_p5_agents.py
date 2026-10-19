from datetime import datetime, timezone
from decimal import Decimal
import pytest

from sidedeck.application.ai_agents import (
    AgentResult, AgentUnavailable, ExternalJsonAgent, normalize_intent,
    research_environment,
)
from sidedeck.bridges.tradingagents_bridge import extract_action


NOW = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)


def test_broker_secrets_never_reach_upstream():
    env = research_environment({
        "SAXO_SIM_ACCESS_TOKEN": "saxo-secret",
        "ALPACA_API_KEY2": "alpaca-secret",
        "ETORO_API_KEY": "etoro-secret",
        "OPENAI_API_KEY": "research-token",
        "PATH": "/bin",
        "PYTHONPATH": "/other-package",
    })
    assert env == {"OPENAI_API_KEY": "research-token", "PATH": "/bin"}


@pytest.mark.parametrize("action", ["BUY", "SELL", "HOLD"])
def test_tradingagents_explicit_actions(action):
    assert extract_action(action) == action
    assert extract_action("FINAL TRANSACTION PROPOSAL: " + action) == action


@pytest.mark.parametrize("action", ["BUY because bullish", "BUY or HOLD", "", "Wait"])
def test_ambiguous_decision_rejected(action):
    with pytest.raises(ValueError):
        extract_action(action)


def test_normalize_agent_intent_is_not_broker_order():
    result = AgentResult("test-upstream", "pinned-revision", "tradingagents",
                         "SOFI", "BUY", "Fundamental research", "")
    intent = normalize_intent(
        result, experiment_id="agent-comparison", strategy_id="multiagent",
        market_timestamp=NOW, decision_timestamp=NOW,
        proposed_shares=Decimal("1"),
    )
    assert intent.portfolio_id == "tradingagents"
    assert intent.instrument_id == "US:SOFI"
    assert intent.quantity == Decimal("1")
    with pytest.raises(ValueError):
        normalize_intent(result, experiment_id="agent-comparison",
                         strategy_id="multiagent", market_timestamp=NOW,
                         decision_timestamp=NOW)


def test_external_runner_requires_real_json(monkeypatch):
    class MockCompleted:
        returncode = 0
        stdout = '{"ticker":"SOFI","decision":"HOLD","rationale":"Wait"}'

    calls = []
    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return MockCompleted()

    monkeypatch.setattr("sidedeck.application.ai_agents.subprocess.run", fake_run)
    agent = ExternalJsonAgent("upstream", "ai-trading", "revision",
                              ("python", "bridge.py"))
    output = agent.run("SOFI", NOW)
    assert output.decision == "HOLD"
    assert calls[0][1]["shell"] if "shell" in calls[0][1] else True
    assert "SAXO_SIM_ACCESS_TOKEN" not in calls[0][1]["env"]


def test_wrong_ticker_fails_closed(monkeypatch):
    class MockCompleted:
        returncode = 0
        stdout = '{"ticker":"AAPL","decision":"BUY","rationale":"Research"}'
    monkeypatch.setattr("sidedeck.application.ai_agents.subprocess.run",
                        lambda *args, **kwargs: MockCompleted())
    with pytest.raises(AgentUnavailable):
        ExternalJsonAgent("upstream", "ai-trading", "revision", ("python",)).run("SOFI", NOW)
