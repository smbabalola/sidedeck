"""Saxo SIM execution accounting, separate from the research ledgers (ADR-003).

One Saxo SIM broker account is split into three logical books. Strategy books
hold EUR cash (account currency) and USD positions (instrument currency).
The unattributed book only records read-only baselines; it never takes fills,
allocations or balancing entries. Nothing here touches the research
``Ledger`` (``tradingagents`` / ``ai-trading``) or the Alpaca paper accounts.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum
from uuid import NAMESPACE_URL, uuid5

ZERO = Decimal("0")
STRATEGY_BOOKS = {"tradingagents": "saxo-sim:tradingagents", "ai-trading": "saxo-sim:ai-trading"}
UNATTRIBUTED_BOOK = "saxo-sim:unattributed"
SIM_BOOKS = (*STRATEGY_BOOKS.values(), UNATTRIBUTED_BOOK)
INITIAL_ALLOCATION_EUR = Decimal("1000")
MAX_POSITION_COST_USD = Decimal("200")
ACCOUNT_CURRENCY = "EUR"
INSTRUMENT_CURRENCY = "USD"
_DECIMAL_FIELDS = ("quantity", "price_usd", "fx_usd_per_eur", "settlement_eur", "fee_amount",
                   "fee_eur", "allocation_eur")


class SimEventType(StrEnum):
    SIM_ALLOCATION = "SIM_ALLOCATION"
    SIM_BUY_FILL = "SIM_BUY_FILL"
    SIM_BASELINE = "SIM_BASELINE"


class SettlementSource(StrEnum):
    BROKER = "BROKER"            # broker-reported account-currency amount
    DERIVED_FX = "DERIVED_FX"    # USD amount / validated EUR/USD of the approved request


class SimAccountingError(ValueError):
    """A SIM accounting invariant was violated; nothing was recorded."""


def book_for_strategy(strategy_id: str) -> str:
    try:
        return STRATEGY_BOOKS[strategy_id]
    except KeyError:
        raise SimAccountingError("unknown SIM strategy") from None


@dataclass(frozen=True)
class SimEvent:
    """Immutable SIM journal entry; money is Decimal with explicit currency."""

    book_id: str
    idempotency_key: str
    event_type: SimEventType
    occurred_at: datetime
    order_key: str | None = None
    broker_execution_id: str | None = None
    instrument_id: str | None = None
    uic: int | None = None
    quantity: Decimal | None = None
    price_usd: Decimal | None = None
    fx_usd_per_eur: Decimal | None = None
    fx_provider: str | None = None
    settlement_eur: Decimal | None = None
    settlement_source: SettlementSource | None = None
    fee_amount: Decimal | None = None
    fee_currency: str | None = None
    fee_eur: Decimal | None = None
    allocation_eur: Decimal | None = None
    approval_ref: str | None = None

    def __post_init__(self) -> None:
        if self.book_id not in SIM_BOOKS:
            raise SimAccountingError("event book is not a Saxo SIM book")
        if not self.idempotency_key or len(self.idempotency_key) > 200:
            raise SimAccountingError("invalid idempotency key")
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise SimAccountingError("SIM event time must be timezone-aware")
        object.__setattr__(self, "occurred_at", self.occurred_at.astimezone(timezone.utc))
        for name in _DECIMAL_FIELDS:
            value = getattr(self, name)
            if value is not None and (not isinstance(value, Decimal) or not value.is_finite()
                                      or value < 0):
                raise SimAccountingError(f"invalid {name}")
        if self.event_type is SimEventType.SIM_ALLOCATION:
            if self.book_id == UNATTRIBUTED_BOOK:
                raise SimAccountingError("the unattributed book never receives an allocation")
            if self.allocation_eur is None or self.allocation_eur <= 0 or not self.approval_ref:
                raise SimAccountingError("allocation needs a positive EUR amount and an approval reference")
        elif self.event_type is SimEventType.SIM_BUY_FILL:
            if self.book_id == UNATTRIBUTED_BOOK:
                raise SimAccountingError("the unattributed book never receives SideDeck fills")
            required = (self.order_key, self.broker_execution_id, self.instrument_id, self.uic,
                        self.quantity, self.price_usd, self.fx_usd_per_eur, self.fx_provider,
                        self.settlement_eur, self.settlement_source, self.fee_amount,
                        self.fee_currency, self.fee_eur, self.approval_ref)
            if any(item is None or item == "" for item in required):
                raise SimAccountingError("fill is missing price, FX, settlement or fee provenance")
            if not self.idempotency_key.startswith("saxo:"):
                raise SimAccountingError("SIM fill keys must be broker-execution scoped")
            if self.fee_currency not in (ACCOUNT_CURRENCY, INSTRUMENT_CURRENCY):
                raise SimAccountingError("fee currency has no approved conversion")
            assert self.quantity is not None and self.price_usd is not None
            if self.quantity <= 0 or self.quantity != self.quantity.to_integral_value():
                raise SimAccountingError("fill quantity must be whole shares")
            if self.price_usd <= 0 or not self.fx_usd_per_eur:
                raise SimAccountingError("fill price and FX must be positive")
        elif self.event_type is SimEventType.SIM_BASELINE:
            if self.book_id != UNATTRIBUTED_BOOK:
                raise SimAccountingError("baselines belong to the unattributed control book only")
            if self.instrument_id is None or self.uic is None or self.quantity is None:
                raise SimAccountingError("baseline needs instrument and quantity")

    @property
    def event_id(self) -> str:
        return str(uuid5(NAMESPACE_URL, f"sidedeck:saxo-sim:{self.book_id}:{self.idempotency_key}"))

    def canonical(self) -> str:
        data: dict[str, object] = {}
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if isinstance(value, datetime):
                value = value.isoformat()
            elif isinstance(value, (Decimal, StrEnum)):
                value = str(value)
            data[name] = value
        return json.dumps(data, sort_keys=True, separators=(",", ":"))

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical().encode("utf-8")).hexdigest()

    @classmethod
    def from_canonical(cls, payload: str) -> "SimEvent":
        data = json.loads(payload)
        for name in _DECIMAL_FIELDS:
            if data.get(name) is not None:
                data[name] = Decimal(data[name])
        data["event_type"] = SimEventType(data["event_type"])
        if data.get("settlement_source") is not None:
            data["settlement_source"] = SettlementSource(data["settlement_source"])
        data["occurred_at"] = datetime.fromisoformat(data["occurred_at"])
        return cls(**data)


@dataclass
class SimPosition:
    uic: int
    quantity: Decimal = ZERO
    cost_usd: Decimal = ZERO
    cost_eur: Decimal = ZERO


@dataclass
class SimBookState:
    book_id: str
    allocation_eur: Decimal = ZERO
    cash_eur: Decimal = ZERO
    fees_eur: Decimal = ZERO
    realized_pnl_eur: Decimal = ZERO
    positions: dict[str, SimPosition] = field(default_factory=dict)
    fill_count: int = 0


class SimLedger:
    """Append-only, idempotent SIM journal with deterministic replay."""

    def __init__(self) -> None:
        self._events: list[SimEvent] = []
        self._keys: dict[tuple[str, str], str] = {}

    @property
    def events(self) -> tuple[SimEvent, ...]:
        return tuple(self._events)

    def check(self, event: SimEvent) -> bool:
        """Validate against current state without recording; False for an exact replay."""
        if not isinstance(event, SimEvent):
            raise SimAccountingError("only SIM events can enter the SIM ledger")
        key = (event.book_id, event.idempotency_key)
        if key in self._keys:
            if self._keys[key] != event.canonical():
                raise SimAccountingError("idempotency key reused with different content")
            return False
        state = self.replay(event.book_id)
        if event.event_type is SimEventType.SIM_ALLOCATION:
            if state.allocation_eur:
                raise SimAccountingError("top-ups need an owner-approved audited allocation; "
                                         "only the initial allocation is supported")
            if event.allocation_eur != INITIAL_ALLOCATION_EUR:
                raise SimAccountingError("initial SIM allocation must be EUR 1,000")
        elif event.event_type is SimEventType.SIM_BUY_FILL:
            if not state.allocation_eur:
                raise SimAccountingError("book has no allocation")
            assert event.settlement_eur is not None and event.fee_eur is not None
            assert event.quantity is not None and event.price_usd is not None
            if state.cash_eur - event.settlement_eur - event.fee_eur < 0:
                raise SimAccountingError("fill exceeds the book's EUR allocation")
            held = state.positions.get(str(event.instrument_id))
            cost = (held.cost_usd if held else ZERO) + event.quantity * event.price_usd
            if cost > MAX_POSITION_COST_USD:
                raise SimAccountingError("position would exceed the USD 200 per-position limit")
        return True

    def append(self, event: SimEvent) -> bool:
        if not self.check(event):
            return False
        self._keys[(event.book_id, event.idempotency_key)] = event.canonical()
        self._events.append(event)
        return True

    def replay(self, book_id: str) -> SimBookState:
        if book_id not in SIM_BOOKS:
            raise SimAccountingError("not a Saxo SIM book")
        state = SimBookState(book_id=book_id)
        for event in self._events:
            if event.book_id != book_id:
                continue
            if event.event_type is SimEventType.SIM_ALLOCATION:
                assert event.allocation_eur is not None
                state.allocation_eur += event.allocation_eur
                state.cash_eur += event.allocation_eur
            elif event.event_type is SimEventType.SIM_BUY_FILL:
                assert event.settlement_eur is not None and event.fee_eur is not None
                assert event.quantity is not None and event.price_usd is not None
                position = state.positions.setdefault(
                    str(event.instrument_id), SimPosition(uic=int(event.uic or 0)))
                position.quantity += event.quantity
                position.cost_usd += event.quantity * event.price_usd
                position.cost_eur += event.settlement_eur
                state.cash_eur -= event.settlement_eur + event.fee_eur
                state.fees_eur += event.fee_eur
                state.fill_count += 1
            elif event.event_type is SimEventType.SIM_BASELINE:
                assert event.quantity is not None
                position = state.positions.setdefault(
                    str(event.instrument_id), SimPosition(uic=int(event.uic or 0)))
                position.quantity += event.quantity
        return state
