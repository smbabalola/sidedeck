"""Portfolio risk screening for non-executable SideDeck proposals."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, ROUND_FLOOR

from sidedeck.application.proposals import evaluate_proposal
from sidedeck.domain.accounting import PortfolioState
from sidedeck.domain.contracts import ExperimentManifest, MarketSnapshot, Side, TradeIntent
from sidedeck.domain.instruments import get_instrument_by_id


@dataclass(frozen=True)
class RiskLimits:
    max_new_position_fraction: Decimal = Decimal("0.20")
    max_gross_exposure_fraction: Decimal = Decimal("0.80")
    cash_reserve_fraction: Decimal = Decimal("0.10")

    def __post_init__(self) -> None:
        for value in (
            self.max_new_position_fraction,
            self.max_gross_exposure_fraction,
            self.cash_reserve_fraction,
        ):
            if not value.is_finite() or value < 0 or value > 1:
                raise ValueError("risk fractions must be finite values between 0 and 1")
        if self.max_new_position_fraction <= 0 or self.max_gross_exposure_fraction <= 0:
            raise ValueError("position and exposure limits must be positive")


@dataclass(frozen=True)
class RiskDecision:
    accepted: bool
    reason: str
    proposed_quantity: Decimal = Decimal("0")


def screen_proposal(
    intent: TradeIntent,
    manifest: ExperimentManifest,
    snapshot: MarketSnapshot,
    portfolio: PortfolioState,
    *,
    max_market_age: timedelta,
    marks: dict[str, MarketSnapshot],
    limits: RiskLimits = RiskLimits(),
) -> RiskDecision:
    """Screen proposal using held-portfolio state. Never sends orders or mutates state.

    Not a fill guarantee: final order stage must recheck buying power, open orders,
    market movements and broker quantity precision.
    """
    proposal = evaluate_proposal(intent, manifest, snapshot, max_market_age=max_market_age)
    if not proposal.accepted:
        return RiskDecision(False, proposal.reason)
    if portfolio.portfolio_id != intent.portfolio_id:
        return RiskDecision(False, "portfolio_state_mismatch")
    if portfolio.cash < 0:
        return RiskDecision(False, "negative_cash")
    if intent.side is Side.HOLD:
        return RiskDecision(True, "hold_no_order")
    try:
        valuation_marks = dict(marks)
        valuation_marks[intent.instrument_id] = snapshot
        nav = portfolio.nav(
            valuation_marks, intent.decision_timestamp, max_market_age
        )
    except (ValueError, KeyError):
        return RiskDecision(False, "unavailable_portfolio_valuation")
    if nav <= 0:
        return RiskDecision(False, "nonpositive_nav")
    instrument = get_instrument_by_id(intent.instrument_id)
    if intent.quantity is not None:
        quantity = intent.quantity
    else:
        assert intent.notional_usd is not None
        quantity = intent.notional_usd / snapshot.price
        quantum = Decimal(1).scaleb(-instrument.quantity_scale)
        quantity = quantity.quantize(quantum, rounding=ROUND_FLOOR)
        if quantity <= 0:
            return RiskDecision(False, "notional_too_small_for_whole_share")
    if not instrument.fractional_allowed and quantity != quantity.to_integral_value():
        return RiskDecision(False, "unsupported_fractional_quantity")
    if quantity.as_tuple().exponent < -instrument.quantity_scale:
        return RiskDecision(False, "quantity_precision_exceeded")
    notional = quantity * snapshot.price
    held = portfolio.positions.get(intent.instrument_id)
    held_quantity = held.quantity if held else Decimal("0")
    if intent.side is Side.SELL:
        if quantity > held_quantity:
            return RiskDecision(False, "insufficient_position")
        return RiskDecision(True, "sell_proposal_only", quantity)
    remaining_cash = portfolio.cash - notional
    if remaining_cash < 0:
        return RiskDecision(False, "insufficient_cash")
    if remaining_cash < nav * limits.cash_reserve_fraction:
        return RiskDecision(False, "cash_reserve_limit")
    existing_value = held_quantity * snapshot.price
    if existing_value + notional > nav * limits.max_new_position_fraction:
        return RiskDecision(False, "position_concentration_limit")
    gross_exposure = sum(
        (position.quantity * valuation_marks[instrument_id].price
         for instrument_id, position in portfolio.positions.items()),
        Decimal("0"),
    )
    if gross_exposure + notional > nav * limits.max_gross_exposure_fraction:
        return RiskDecision(False, "gross_exposure_limit")
    return RiskDecision(True, "buy_proposal_only", quantity)
