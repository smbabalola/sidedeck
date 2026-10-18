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
    "ValidationResult",
]
