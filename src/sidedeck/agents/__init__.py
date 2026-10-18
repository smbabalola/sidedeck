"""Proposal-only, fixture-backed agent adapters for P2A."""

from .audit import AuditStore, InMemoryAuditStore, SqlAuditStore
from .contracts import (
    AgentProposalEnvelope,
    AgentRunRecord,
    AgentRunRequest,
    EvidenceReference,
    MarketBundle,
    ValidationResult,
)
from .fixtures import AITradingFixtureWorker, TradingAgentsFixtureWorker
from .gateway import AgentRunCoordinator, ProposalSchemaValidator
from .tradingagents_preparation import TradingAgentsPreparation
from .tradingagents_adapter import TradingAgentsAdapterBlocked, TradingAgentsProposalAdapter

__all__ = [
    "AITradingFixtureWorker",
    "AgentProposalEnvelope",
    "AgentRunCoordinator",
    "AgentRunRecord",
    "AgentRunRequest",
    "AuditStore",
    "EvidenceReference",
    "InMemoryAuditStore",
    "MarketBundle",
    "ProposalSchemaValidator",
    "SqlAuditStore",
    "TradingAgentsFixtureWorker",
    "TradingAgentsPreparation",
    "TradingAgentsAdapterBlocked",
    "TradingAgentsProposalAdapter",
    "ValidationResult",
]
