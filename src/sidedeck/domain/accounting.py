from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from .contracts import EventType, LedgerEvent, MarketSnapshot, Posting, ZERO
from .instruments import get_instrument, validate_quantity


@dataclass
class Position:
    quantity: Decimal = ZERO
    cost_basis: Decimal = ZERO


@dataclass
class PortfolioState:
    portfolio_id: str
    cash: Decimal = ZERO
    positions: dict[str, Position] = field(default_factory=dict)
    realized_gross: Decimal = ZERO
    fees: Decimal = ZERO

    @property
    def realized_net(self) -> Decimal:
        return self.realized_gross - self.fees

    def nav(self, marks: dict[str, MarketSnapshot]) -> Decimal:
        total = self.cash
        for instrument_id, position in self.positions.items():
            if instrument_id not in marks:
                raise ValueError(f"missing mark for {instrument_id}")
            total += position.quantity * marks[instrument_id].price
        return total


class Ledger:
    """Append-only in-memory journal with deterministic replay and idempotency."""

    def __init__(self) -> None:
        self._events: list[LedgerEvent] = []
        self._keys: set[tuple[str, str]] = set()

    @property
    def events(self) -> tuple[LedgerEvent, ...]:
        return tuple(self._events)

    def append(self, event: LedgerEvent) -> bool:
        key = (event.portfolio_id, event.idempotency_key)
        if key in self._keys:
            return False
        prior = [old for old in self._events if old.portfolio_id == event.portfolio_id]
        if prior and event.occurred_at < prior[-1].occurred_at:
            raise ValueError("events must be appended in occurrence order")
        if event.event_type is EventType.OPENING_CAPITAL and any(
            old.portfolio_id == event.portfolio_id and old.event_type is EventType.OPENING_CAPITAL
            for old in self._events
        ):
            raise ValueError("opening capital can only be recorded once per portfolio")
        if event.event_type is not EventType.OPENING_CAPITAL and not any(
            old.portfolio_id == event.portfolio_id and old.event_type is EventType.OPENING_CAPITAL
            for old in self._events
        ):
            raise ValueError("portfolio must be opened before activity")
        self._events.append(event)
        self._keys.add(key)
        try:
            self.replay(event.portfolio_id)
        except Exception:
            self._events.pop()
            self._keys.remove(key)
            raise
        return True

    def replay(self, portfolio_id: str) -> PortfolioState:
        state = PortfolioState(portfolio_id=portfolio_id)
        for event in self._events:
            if event.portfolio_id == portfolio_id:
                self._apply(state, event)
        if state.cash < ZERO:
            raise ValueError("replay produced negative cash")
        return state

    @staticmethod
    def _apply(state: PortfolioState, event: LedgerEvent) -> None:
        if event.event_type is EventType.OPENING_CAPITAL:
            state.cash += sum((p.debit for p in event.postings if p.account == "cash"), ZERO)
            return
        if event.event_type is EventType.BUY_FILL:
            assert event.instrument_id and event.quantity and event.price
            gross = event.quantity * event.price
            state.cash -= gross + event.fee
            position = state.positions.setdefault(event.instrument_id, Position())
            position.quantity += event.quantity
            position.cost_basis += gross
            state.fees += event.fee
        elif event.event_type is EventType.SELL_FILL:
            assert event.instrument_id and event.quantity and event.price
            position = state.positions.get(event.instrument_id, Position())
            if position.quantity < event.quantity:
                raise ValueError("cannot sell more than the portfolio owns")
            gross = event.quantity * event.price
            average_cost = position.cost_basis / position.quantity
            state.cash += gross - event.fee
            position.quantity -= event.quantity
            position.cost_basis -= average_cost * event.quantity
            state.realized_gross += gross - average_cost * event.quantity
            state.fees += event.fee
            if position.quantity == ZERO:
                del state.positions[event.instrument_id]

    def rebuild(self) -> dict[str, PortfolioState]:
        return {portfolio_id: self.replay(portfolio_id) for portfolio_id in {e.portfolio_id for e in self._events}}


def opening_event(portfolio_id: str, at: datetime, amount: Decimal = Decimal("1000")) -> LedgerEvent:
    if amount != Decimal("1000"):
        raise ValueError("P1 portfolios must open with exactly USD 1,000")
    return LedgerEvent(
        portfolio_id=portfolio_id,
        idempotency_key="opening-capital",
        occurred_at=at,
        event_type=EventType.OPENING_CAPITAL,
        postings=(Posting(account="cash", debit=amount), Posting(account="equity", credit=amount)),
    )


def fill_event(
    portfolio_id: str,
    key: str,
    event_type: EventType,
    instrument_id: str,
    quantity: Decimal,
    price: Decimal,
    at: datetime,
    fee: Decimal = ZERO,
) -> LedgerEvent:
    instrument = get_instrument(instrument_id.split(":", 1)[-1])
    validate_quantity(instrument, quantity)
    gross = quantity * price
    if event_type is EventType.BUY_FILL:
        postings = (
            Posting(account=f"position:{instrument_id}", debit=gross),
            *( (Posting(account="fees", debit=fee),) if fee else () ),
            Posting(account="cash", credit=gross + fee),
        )
    elif event_type is EventType.SELL_FILL:
        postings = (
            Posting(account="cash", debit=gross - fee),
            *( (Posting(account="fees", debit=fee),) if fee else () ),
            Posting(account=f"position:{instrument_id}", credit=gross),
        )
    else:
        raise ValueError("fill event must be BUY_FILL or SELL_FILL")
    return LedgerEvent(
        portfolio_id=portfolio_id,
        idempotency_key=key,
        occurred_at=at,
        event_type=event_type,
        postings=postings,
        instrument_id=instrument_id,
        quantity=quantity,
        price=price,
        fee=fee,
    )
