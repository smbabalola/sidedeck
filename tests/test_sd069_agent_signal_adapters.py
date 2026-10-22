"""SD-069 agent adapters. Records are hand-written fixtures, not model outputs."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from sidedeck.application.p5_agents import AI_HEDGE_FUND_REVISION, TRADINGAGENTS_REVISION
from sidedeck.application.sd069_agent_signal_adapters import (
    adapt_agent_record,
    research_candidates,
)
from sidedeck.application.sd070_research_signal import SignalError

NOW = datetime(2026, 10, 22, 19, tzinfo=UTC)
ALLOWED = {"US:MSFT"}


def _ta(**kw: Any) -> dict[str, Any]:
    rec: dict[str, Any] = {
        "portfolio": "tradingagents", "ticker": "MSFT", "upstream": "TauricResearch/TradingAgents",
        "status": "RESEARCH_ONLY", "decision": "BUY", "rationale": "fixture rationale",
        "instrument_id": "US:MSFT", "market_cutoff": (NOW - timedelta(days=1)).isoformat(),
        "decision_timestamp": (NOW - timedelta(hours=1)).isoformat(),
        "upstream_version": TRADINGAGENTS_REVISION, "model_config_fingerprint": "f" * 64,
        "model_provider": "openai", "model_id": "fixture-model",
        "evidence_references": ["10-K 2026", "price bundle"], "abstained": False,
        "unavailable": False,
    }
    rec.update(kw)
    return rec


def test_buy_becomes_swing_long_with_versions_and_evidence() -> None:
    out = adapt_agent_record(_ta(), invoked="tradingagents", allowed_ids=ALLOWED, now=NOW)
    assert out.status == "SIGNAL" and out.signal is not None
    s = out.signal
    assert (s.track, s.direction, s.source_kind) == ("SWING", "LONG", "TRADINGAGENTS")
    assert TRADINGAGENTS_REVISION in s.source_version and "openai/fixture-model" in s.source_version
    assert s.evidence[0].sha256 == out.output_sha256 and len(s.evidence) == 3
    assert all(c.startswith("SIDEDECK_PROCEDURAL") for c in s.invalidation)


def test_buffett_maps_to_position_and_hold_to_neutral() -> None:
    rec = _ta(portfolio="ai-trading", upstream="virattt/ai-hedge-fund", decision="HOLD",
              upstream_version=AI_HEDGE_FUND_REVISION)
    out = adapt_agent_record(rec, invoked="ai-trading", allowed_ids=ALLOWED, now=NOW)
    assert out.signal and out.signal.track == "POSITION" and out.signal.direction == "NEUTRAL"


def test_abstention_and_unavailable_are_preserved() -> None:
    abst = adapt_agent_record(_ta(abstained=True), invoked="tradingagents", allowed_ids=ALLOWED,
                              now=NOW)
    assert abst.status == "ABSTAINED" and abst.signal and abst.signal.direction == "ABSTAIN"
    blocked = {"portfolio": "tradingagents", "upstream": "TauricResearch/TradingAgents",
               "status": "BLOCKED", "reason": "AgentUnavailable"}
    out = adapt_agent_record(blocked, invoked="tradingagents", allowed_ids=ALLOWED, now=NOW)
    assert out.status == "UNAVAILABLE" and out.signal is None and out.reason == "AgentUnavailable"


@pytest.mark.parametrize("change, invoked, reason", [
    ({"portfolio": "ai-trading"}, "tradingagents", "identity"),
    ({"upstream": "someone/else"}, "tradingagents", "identity"),
    ({}, "ai-trading", "identity"),
    ({"instrument_id": "US:TSLA", "ticker": "TSLA"}, "tradingagents", "shortlist"),
    ({"instrument_id": "US:TSLA"}, "tradingagents", "disagree"),
    ({"upstream_version": None}, "tradingagents", "pinned"),
    ({"upstream_version": "tradingagents==9.9"}, "tradingagents", "pinned"),
    ({"market_cutoff": None}, "tradingagents", "cutoff"),
    ({"decision": "STRONG_BUY"}, "tradingagents", "BUY, SELL or HOLD"),
    ({"market_cutoff": NOW.isoformat(), "decision_timestamp": (NOW - timedelta(hours=1)).isoformat()},
     "tradingagents", "look-ahead"),
    ({"decision_timestamp": (NOW + timedelta(hours=1)).isoformat()}, "tradingagents", "future"),
])
def test_refusals(change: dict[str, Any], invoked: str, reason: str) -> None:
    out = adapt_agent_record(_ta(**change), invoked=invoked, allowed_ids=ALLOWED, now=NOW)
    assert out.status == "REFUSED" and reason in out.reason and out.signal is None


def test_unknown_adapter_and_research_batching() -> None:
    with pytest.raises(SignalError):
        adapt_agent_record(_ta(), invoked="chatgpt", allowed_ids=ALLOWED, now=NOW)
    assert research_candidates(["US:A", "US:B", "US:C"], ["US:B"], 5) == ("US:A", "US:C")
    with pytest.raises(SignalError):
        research_candidates(["US:A"], [], 31)
