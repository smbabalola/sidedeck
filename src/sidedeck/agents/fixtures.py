from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Protocol

from .contracts import AgentProposalEnvelope, AgentRunRequest, EvidenceReference, MarketBundle
from sidedeck.domain.contracts import Side, TradeIntent


class FixtureWorker(Protocol):
    adapter_id: str
    revision: str

    def propose(self, request: AgentRunRequest, bundle: MarketBundle) -> AgentProposalEnvelope: ...


def _inputs_hash(request: AgentRunRequest, bundle: MarketBundle) -> str:
    payload = {
        "request": request.model_dump(mode="json"),
        "bundle": bundle.model_dump(mode="json"),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class TradingAgentsFixtureWorker:
    adapter_id = "tradingagents.fixture"
    revision = "fixture-1"

    def __init__(self, rejected: bool = False) -> None:
        self.rejected = rejected

    def propose(self, request: AgentRunRequest, bundle: MarketBundle) -> AgentProposalEnvelope:
        now = bundle.decision_cutoff_utc
        if self.rejected:
            return AgentProposalEnvelope(
                run_id=request.run_id,
                portfolio_id=request.portfolio_id,
                adapter_id=self.adapter_id,
                generated_at=now,
                data_as_of=now,
                model_revision=self.revision,
                decision_inputs_hash=_inputs_hash(request, bundle),
                prompt_version="fixture-prompt-1",
                result="FAILED",
                explanation="deterministic fixture refusal",
                errors=("FIXTURE_REFUSAL",),
                runtime_ms=1,
            )
        intent = TradeIntent(
            experiment_id=request.experiment_id,
            portfolio_id=request.portfolio_id,
            strategy_id=request.strategy_id,
            instrument_id="US:AAPL",
            side=Side.BUY,
            quantity=Decimal("1"),
            rationale="deterministic fixture momentum proposal",
            model_revision=self.revision,
            decision_timestamp=now,
            data_as_of=now,
        )
        return AgentProposalEnvelope(
            run_id=request.run_id,
            portfolio_id=request.portfolio_id,
            adapter_id=self.adapter_id,
            generated_at=now,
            data_as_of=now,
            model_revision=self.revision,
            decision_inputs_hash=_inputs_hash(request, bundle),
            prompt_version="fixture-prompt-1",
            proposals=(intent,),
            evidence=(EvidenceReference(reference=bundle.bundle_id, as_of=now, kind="fixture"),),
            explanation="deterministic TradingAgents-shaped proposal",
            runtime_ms=1,
        )


class AITradingFixtureWorker:
    adapter_id = "ai-trading.protocol-fixture"
    revision = "independent-protocol-1"

    def __init__(self, rejected: bool = False) -> None:
        self.rejected = rejected

    def propose(self, request: AgentRunRequest, bundle: MarketBundle) -> AgentProposalEnvelope:
        now = bundle.decision_cutoff_utc
        return AgentProposalEnvelope(
            run_id=request.run_id,
            portfolio_id=request.portfolio_id,
            adapter_id=self.adapter_id,
            generated_at=now,
            data_as_of=now,
            model_revision=self.revision,
            decision_inputs_hash=_inputs_hash(request, bundle),
            prompt_version="fixture-prompt-1",
            evidence=(EvidenceReference(reference=bundle.bundle_id, as_of=now, kind="fixture"),),
            result="FAILED" if self.rejected else "HOLD",
            explanation="independent protocol fixture has no trade proposal",
            errors=("FIXTURE_REFUSAL",) if self.rejected else (),
            runtime_ms=1,
        )
