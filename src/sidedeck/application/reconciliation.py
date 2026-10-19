"""Compare broker paper positions with the combined internal experiment portfolios."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sidedeck.domain.accounting import PortfolioState
from sidedeck.domain.contracts import AUTHORIZED_PORTFOLIOS
from sidedeck.infrastructure.alpaca_readonly import PaperPosition


@dataclass(frozen=True)
class PositionDifference:
    symbol: str
    internal_quantity: Decimal
    broker_quantity: Decimal


@dataclass(frozen=True)
class ReconciliationReport:
    matched: bool
    differences: tuple[PositionDifference, ...]


def reconcile_positions(
    portfolios: dict[str, PortfolioState],
    broker_positions: tuple[PaperPosition, ...],
) -> ReconciliationReport:
    if set(portfolios) != set(AUTHORIZED_PORTFOLIOS):
        raise ValueError("both experiment portfolios must be supplied")
    internal: dict[str, Decimal] = {}
    for portfolio_id, state in portfolios.items():
        if state.portfolio_id != portfolio_id:
            raise ValueError("portfolio identity mismatch")
        for instrument_id, position in state.positions.items():
            if not instrument_id.startswith("US:") or not position.quantity.is_finite() or position.quantity < 0:
                raise ValueError("invalid internal position")
            symbol = instrument_id.removeprefix("US:")
            internal[symbol] = internal.get(symbol, Decimal("0")) + position.quantity
    broker: dict[str, Decimal] = {}
    for position in broker_positions:
        if not position.quantity.is_finite() or position.quantity <= 0 or position.symbol in broker:
            raise ValueError("invalid broker position")
        broker[position.symbol] = position.quantity
    diffs = tuple(
        PositionDifference(symbol, internal.get(symbol, Decimal("0")), broker.get(symbol, Decimal("0")))
        for symbol in sorted(set(internal) | set(broker))
        if internal.get(symbol, Decimal("0")) != broker.get(symbol, Decimal("0"))
    )
    return ReconciliationReport(not diffs, diffs)
