from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from .accounting import PortfolioState
from .contracts import MarketSnapshot, Side, TradeIntent, ZERO
from .instruments import get_instrument_by_id, validate_quantity
from .market import validate_snapshot


class RiskReason(StrEnum):
    ACCEPTED = "ACCEPTED"
    HOLD = "HOLD"
    UNKNOWN_INSTRUMENT = "UNKNOWN_INSTRUMENT"
    STALE_MARK = "STALE_MARK"
    POSITION_CAP = "POSITION_CAP"
    EXPOSURE_CAP = "EXPOSURE_CAP"
    MAX_POSITIONS = "MAX_POSITIONS"
    INSUFFICIENT_CASH = "INSUFFICIENT_CASH"
    MISSING_STOP = "MISSING_STOP"
    STOP_RISK_BUDGET = "STOP_RISK_BUDGET"
    SHORT_OR_SELL_UNOWNED = "SHORT_OR_SELL_UNOWNED"


@dataclass(frozen=True)
class RiskPolicy:
    version: str = "risk-policy-1"
    max_position_pct: Decimal = Decimal("0.20")
    max_exposure_pct: Decimal = Decimal("0.80")
    max_positions: int = 4
    risk_budget_pct: Decimal = Decimal("0.01")
    max_snapshot_age_seconds: int = 86400
    fee_rate: Decimal = Decimal("0.001")
    spread_bps: Decimal = Decimal("5")


@dataclass(frozen=True)
class RiskDecision:
    decision_id: UUID
    intent_id: UUID
    accepted: bool
    reason: RiskReason
    policy_version: str
    requested_notional: Decimal
    projected_exposure: Decimal
    stop_risk: Decimal


class RiskGate:
    def __init__(self, policy: RiskPolicy | None = None) -> None:
        self.policy = policy or RiskPolicy()

    def evaluate(
        self,
        intent: TradeIntent,
        state: PortfolioState,
        snapshot: MarketSnapshot,
        *,
        portfolio_value: Decimal,
        marks: dict[str, MarketSnapshot] | None = None,
    ) -> RiskDecision:
        execution_price = self._execution_price(intent.side, snapshot.price)
        requested = intent.notional_usd or ((intent.quantity or ZERO) * execution_price)
        market_requested = intent.notional_usd or ((intent.quantity or ZERO) * snapshot.price)
        fees = (requested * self.policy.fee_rate).quantize(Decimal("0.01"))
        current_values = self._current_values(state, marks or {snapshot.instrument_id: snapshot})
        existing_position_value = current_values.get(intent.instrument_id, ZERO)
        projected = sum(current_values.values(), ZERO)
        if intent.side is Side.BUY:
            projected += market_requested
        elif intent.side is Side.SELL:
            projected -= min(existing_position_value, market_requested)
        reject = self._reject_reason(
            intent, state, snapshot, portfolio_value, requested, projected,
            existing_position_value, fees,
            market_requested,
        )
        return RiskDecision(
            decision_id=uuid4(),
            intent_id=uuid4(),
            accepted=reject is None,
            reason=RiskReason.ACCEPTED if reject is None else reject,
            policy_version=self.policy.version,
            requested_notional=requested,
            projected_exposure=projected,
            stop_risk=self._stop_risk(intent, snapshot),
        )

    def _reject_reason(
        self,
        intent: TradeIntent,
        state: PortfolioState,
        snapshot: MarketSnapshot,
        portfolio_value: Decimal,
        requested: Decimal,
        projected: Decimal,
        existing_position_value: Decimal,
        fees: Decimal,
        market_requested: Decimal,
    ) -> RiskReason | None:
        try:
            instrument = get_instrument_by_id(intent.instrument_id)
            validate_snapshot(snapshot, intent.data_as_of, timedelta(seconds=self.policy.max_snapshot_age_seconds))
            if snapshot.instrument_id != intent.instrument_id:
                return RiskReason.UNKNOWN_INSTRUMENT
            if intent.quantity is not None:
                validate_quantity(instrument, intent.quantity)
        except ValueError:
            return RiskReason.STALE_MARK
        if intent.side is Side.HOLD:
            return RiskReason.HOLD
        if intent.stop_price is None or not intent.invalidation:
            return RiskReason.MISSING_STOP
        if portfolio_value <= ZERO:
            return RiskReason.INSUFFICIENT_CASH
        if intent.side is Side.BUY:
            if state.cash < requested + fees:
                return RiskReason.INSUFFICIENT_CASH
            if existing_position_value + market_requested > portfolio_value * self.policy.max_position_pct:
                return RiskReason.POSITION_CAP
            if projected > portfolio_value * self.policy.max_exposure_pct:
                return RiskReason.EXPOSURE_CAP
            if intent.instrument_id not in state.positions and len(state.positions) >= self.policy.max_positions:
                return RiskReason.MAX_POSITIONS
            stop_risk = (snapshot.price - intent.stop_price) * (intent.quantity or ZERO)
            if stop_risk < ZERO or stop_risk > portfolio_value * self.policy.risk_budget_pct:
                return RiskReason.STOP_RISK_BUDGET
        else:
            position = state.positions.get(intent.instrument_id)
            if position is None or position.quantity < (intent.quantity or ZERO):
                return RiskReason.SHORT_OR_SELL_UNOWNED
        return None

    @staticmethod
    def _stop_risk(intent: TradeIntent, snapshot: MarketSnapshot) -> Decimal:
        if intent.stop_price is None or intent.quantity is None:
            return ZERO
        return max(ZERO, (snapshot.price - intent.stop_price) * intent.quantity)

    def _execution_price(self, side: Side, price: Decimal) -> Decimal:
        spread = self.policy.spread_bps / Decimal("10000")
        return price * (Decimal("1") + spread if side is Side.BUY else Decimal("1") - spread)

    @staticmethod
    def _current_values(
        state: PortfolioState, marks: dict[str, MarketSnapshot]
    ) -> dict[str, Decimal]:
        values: dict[str, Decimal] = {}
        for instrument_id, position in state.positions.items():
            mark = marks.get(instrument_id)
            if mark is None:
                raise ValueError(f"missing mark for held position {instrument_id}")
            values[instrument_id] = position.quantity * mark.price
        return values
