"""Pure, fail-closed trade proposal gate. Does not create orders or contact brokers."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from sidedeck.domain.contracts import ExperimentManifest, MarketSnapshot, Side, TradeIntent
from sidedeck.domain.instruments import get_instrument_by_id, validate_quantity
from sidedeck.domain.market import validate_snapshot


@dataclass(frozen=True)
class ProposalDecision:
    accepted: bool
    reason: str
    intent: TradeIntent | None = None


def evaluate_proposal(
    intent: TradeIntent,
    manifest: ExperimentManifest,
    snapshot: MarketSnapshot,
    *,
    max_market_age: timedelta,
) -> ProposalDecision:
    """Validate an untrusted strategy suggestion; acceptance never authorizes execution.

    The caller must independently enforce cash/holdings limits if an order stage
    is ever introduced. No network, broker, order, or portfolio mutation occurs.
    """
    if intent.experiment_id != manifest.experiment_id:
        return ProposalDecision(False, "experiment_mismatch")
    if intent.portfolio_id not in manifest.portfolio_ids:
        return ProposalDecision(False, "portfolio_not_authorized")
    if intent.instrument_id not in manifest.instruments:
        return ProposalDecision(False, "instrument_not_in_experiment")
    if intent.decision_timestamp < manifest.created_at:
        return ProposalDecision(False, "decision_before_experiment")
    if intent.instrument_id != snapshot.instrument_id:
        return ProposalDecision(False, "snapshot_instrument_mismatch")
    if intent.data_as_of != snapshot.market_timestamp:
        return ProposalDecision(False, "snapshot_asof_mismatch")
    try:
        instrument = get_instrument_by_id(intent.instrument_id)
        validate_snapshot(snapshot, intent.decision_timestamp, max_market_age)
        if intent.side is not Side.HOLD:
            if intent.quantity is not None:
                validate_quantity(instrument, intent.quantity)
            else:
                assert intent.notional_usd is not None
                if intent.notional_usd < Decimal("0.01"):
                    return ProposalDecision(False, "notional_below_minimum")
    except (ValueError, KeyError) as exc:
        return ProposalDecision(False, f"validation_failed:{type(exc).__name__}")
    return ProposalDecision(True, "proposal_only", intent)
