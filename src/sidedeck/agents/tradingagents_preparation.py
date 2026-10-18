from __future__ import annotations

from dataclasses import dataclass

from .contracts import AgentProposalEnvelope, AgentRunRequest, MarketBundle
from .fixtures import TradingAgentsFixtureWorker


@dataclass(frozen=True)
class TradingAgentsPreparation:
    """Offline adapter preparation; it deliberately performs no upstream import or call."""

    repository: str = "TauricResearch/TradingAgents"
    pinned_sha: str = "e8f5503e9b86d5c2710b0c76b1f686703968c9df"
    entrypoint: str = "TradingAgentsGraph.propagate"
    network_enabled: bool = False
    broker_tools_enabled: bool = False
    model_credentials_required: bool = True

    def fixture_smoke(self, request: AgentRunRequest, bundle: MarketBundle) -> AgentProposalEnvelope:
        """Return only the independent deterministic fixture until opt-in gates are met."""
        if request.adapter_id != "tradingagents.fixture":
            raise ValueError("offline preparation accepts only the fixture adapter")
        return TradingAgentsFixtureWorker().propose(request, bundle)
