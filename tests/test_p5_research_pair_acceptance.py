import pytest

from sidedeck.application.p5_research_pair_acceptance import assess_research_pair


def evidence():
    return [
        {"portfolio": "tradingagents", "upstream": "TauricResearch/TradingAgents",
         "ticker": "SOFI", "status": "RESEARCH_ONLY", "decision": "HOLD",
         "rationale": "Independent fundamental analysis", "model_config_fingerprint": "rev1",
         "model_id": "model-a", "model_provider": "ollama", "strategy_id": "dual-agent",
         "instrument_id": "US:SOFI", "upstream_version": "0.7.0",
         "market_cutoff": "2026-10-19T12:00:00+00:00",
         "decision_timestamp": "2026-10-19T12:01:00+00:00",
         "evidence_references": ["fixture:market"], "abstained": False, "unavailable": False},
        {"portfolio": "ai-trading", "upstream": "virattt/ai-hedge-fund",
         "ticker": "SOFI", "status": "RESEARCH_ONLY", "decision": "SELL",
         "rationale": "Independent valuation model", "model_config_fingerprint": "rev1",
         "model_id": "model-b", "model_provider": "ollama", "strategy_id": "dual-agent",
         "instrument_id": "US:SOFI", "upstream_version": "v2",
         "market_cutoff": "2026-10-19T12:00:00+00:00",
         "decision_timestamp": "2026-10-19T12:02:00+00:00",
         "evidence_references": ["fixture:sec"], "abstained": False, "unavailable": False},
    ]


def test_paired_evidence_remains_proposal_only():
    result = assess_research_pair(evidence(), "SOFI")
    assert result["order_submission_allowed"] is False
    assert result["broker_execution"] == "DISABLED"
    assert result["research_pair_status"] == "RECORDED_NOT_RISK_APPROVED"


@pytest.mark.parametrize("field", ["market_cutoff", "decision_timestamp", "evidence_references",
                                    "upstream_version", "strategy_id", "instrument_id"])
def test_rich_research_lineage_is_required(field):
    items = evidence()
    items[0].pop(field)
    with pytest.raises(ValueError):
        assess_research_pair(items, "SOFI")


def test_abstention_cannot_become_hold():
    items = evidence()
    items[1]["abstained"] = True
    items[1]["decision"] = "HOLD"
    with pytest.raises(ValueError, match="abstention"):
        assess_research_pair(items, "SOFI")


def test_market_cutoffs_must_match():
    items = evidence()
    items[1]["market_cutoff"] = "2026-10-19T12:05:00+00:00"
    with pytest.raises(ValueError, match="cutoff"):
        assess_research_pair(items, "SOFI")


@pytest.mark.parametrize("mutation", [
    lambda items: items.pop(),
    lambda items: items[0].update({"ticker": "AAPL"}),
    lambda items: items[0].update({"status": "BLOCKED"}),
    lambda items: items[1].update({"rationale": ""}),
    lambda items: items[1].update({"model_config_fingerprint": "different"}),
    lambda items: items[1].update({"portfolio": "tradingagents"}),
])
def test_invalid_paired_evidence_fails_closed(mutation):
    items = evidence()
    mutation(items)
    with pytest.raises(ValueError):
        assess_research_pair(items, "SOFI")
