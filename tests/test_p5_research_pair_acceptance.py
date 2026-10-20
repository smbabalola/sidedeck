import pytest

from sidedeck.application.p5_research_pair_acceptance import assess_research_pair


def evidence():
    return [
        {"portfolio": "tradingagents", "upstream": "TauricResearch/TradingAgents",
         "ticker": "SOFI", "status": "RESEARCH_ONLY", "decision": "HOLD",
         "rationale": "Independent fundamental analysis", "model_config_fingerprint": "rev1",
         "model_id": "model-a"},
        {"portfolio": "ai-trading", "upstream": "virattt/ai-hedge-fund",
         "ticker": "SOFI", "status": "RESEARCH_ONLY", "decision": "SELL",
         "rationale": "Independent valuation model", "model_config_fingerprint": "rev1",
         "model_id": "model-b"},
    ]


def test_paired_evidence_remains_proposal_only():
    result = assess_research_pair(evidence(), "SOFI")
    assert result["order_submission_allowed"] is False
    assert result["broker_execution"] == "DISABLED"
    assert result["research_pair_status"] == "RECORDED_NOT_RISK_APPROVED"


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
