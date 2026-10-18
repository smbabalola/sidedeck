from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import hashlib
import json
from typing import Any, Protocol

from .contracts import AgentProposalEnvelope, AgentRunRequest, EvidenceReference, MarketBundle
from sidedeck.domain.contracts import Side, TradeIntent


class TradingAgentsGraph(Protocol):
    def propagate(self, ticker: str, trade_date: str) -> tuple[Any, Any]: ...


class TradingAgentsAdapterBlocked(RuntimeError):
    """The optional upstream runtime is unavailable or not explicitly enabled."""


class TradingAgentsProposalAdapter:
    """Proposal-only boundary for the pinned TradingAgentsGraph API.

    The graph is injected by an owner-controlled environment. This package does
    not import, install, configure, or network to TradingAgents by default.
    """

    adapter_id = "tradingagents.upstream"
    upstream_sha = "e8f5503e9b86d5c2710b0c76b1f686703968c9df"
    status = "CODE_READY"

    def __init__(self, graph: TradingAgentsGraph | None = None, *, enabled: bool = False) -> None:
        self.graph = graph
        self.enabled = enabled

    def propose(self, request: AgentRunRequest, bundle: MarketBundle) -> AgentProposalEnvelope:
        if not self.enabled or self.graph is None:
            raise TradingAgentsAdapterBlocked(
                "upstream model/data execution is disabled; use the fixture adapter offline"
            )
        ticker = self._single_ticker(request, bundle)
        _, decision = self.graph.propagate(ticker, bundle.decision_cutoff_utc.date().isoformat())
        return self.normalize_decision(request, bundle, decision)

    def normalize_decision(
        self, request: AgentRunRequest, bundle: MarketBundle, decision: Any
    ) -> AgentProposalEnvelope:
        now = bundle.decision_cutoff_utc
        inputs_hash = self._input_hash(request, bundle)
        evidence = (EvidenceReference(reference="TradingAgentsGraph.propagate", as_of=now, kind="local"),)
        if not isinstance(decision, dict):
            return self._blocked(request, bundle, now, evidence, "UPSTREAM_DECISION_NOT_STRUCTURED")
        if any(key in decision for key in ("broker", "order", "execute", "endpoint", "credential")):
            return self._blocked(request, bundle, now, evidence, "BROKER_OR_CREDENTIAL_FIELD")
        action = str(decision.get("action", decision.get("signal", "HOLD"))).upper()
        if action in {"HOLD", "WAIT", "NONE"}:
            return AgentProposalEnvelope(
                run_id=request.run_id, portfolio_id=request.portfolio_id, adapter_id=self.adapter_id,
                generated_at=now, data_as_of=now, model_revision=request.adapter_revision,
                upstream_sha=self.upstream_sha, decision_inputs_hash=inputs_hash,
                prompt_version="upstream-proposal-v1", evidence=evidence, result="HOLD",
                explanation="TradingAgents returned no executable proposal",
            )
        if action not in {"BUY", "SELL"}:
            return self._blocked(request, bundle, now, evidence, "UNSUPPORTED_ACTION")
        ticker = str(decision.get("ticker", "")).upper()
        instrument_id = f"US:{ticker}"
        quantity = decision.get("quantity")
        stop_price = decision.get("stop_price")
        invalidation = decision.get("invalidation")
        if not ticker or quantity is None or stop_price is None or not invalidation:
            return self._blocked(request, bundle, now, evidence, "MISSING_SIZE_OR_STOP")
        try:
            intent = TradeIntent(
                experiment_id=request.experiment_id, portfolio_id=request.portfolio_id,
                strategy_id=request.strategy_id, instrument_id=instrument_id,
                side=Side(action), quantity=Decimal(str(quantity)),
                rationale=str(decision.get("rationale", "TradingAgents proposal")),
                model_revision=request.adapter_revision, decision_timestamp=now, data_as_of=now,
                stop_price=Decimal(str(stop_price)), invalidation=str(invalidation),
            )
        except (TypeError, ValueError, ArithmeticError):
            return self._blocked(request, bundle, now, evidence, "INVALID_PROPOSAL_FIELDS")
        return AgentProposalEnvelope(
            run_id=request.run_id, portfolio_id=request.portfolio_id, adapter_id=self.adapter_id,
            generated_at=now, data_as_of=now, model_revision=request.adapter_revision,
            upstream_sha=self.upstream_sha, decision_inputs_hash=self._input_hash(request, bundle),
            prompt_version="upstream-proposal-v1", proposals=(intent,), evidence=evidence,
            explanation="normalized TradingAgents proposal; SideDeck risk gate remains authoritative",
        )

    @staticmethod
    def _single_ticker(request: AgentRunRequest, bundle: MarketBundle) -> str:
        if len(request.allowed_instruments) != 1 or request.allowed_instruments != bundle.allowed_instruments:
            raise TradingAgentsAdapterBlocked("upstream adapter requires exactly one approved instrument")
        return request.allowed_instruments[0][3:]

    def _blocked(
        self, request: AgentRunRequest, bundle: MarketBundle, now: datetime,
        evidence: tuple[EvidenceReference, ...], reason: str
    ) -> AgentProposalEnvelope:
        return AgentProposalEnvelope(
            run_id=request.run_id, portfolio_id=request.portfolio_id, adapter_id=self.adapter_id,
            generated_at=now, data_as_of=now, model_revision=request.adapter_revision,
            upstream_sha=self.upstream_sha, decision_inputs_hash=self._input_hash(request, bundle),
            prompt_version="upstream-proposal-v1", evidence=evidence, result="FAILED",
            explanation="blocked until the proposal is structurally safe", errors=(reason,),
        )

    @staticmethod
    def _input_hash(request: AgentRunRequest, bundle: MarketBundle) -> str:
        return hashlib.sha256(
            json.dumps(
                {"request": request.model_dump(mode="json"), "bundle": bundle.model_dump(mode="json")},
                sort_keys=True, separators=(",", ":"),
            ).encode()
        ).hexdigest()
