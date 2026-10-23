from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum
import json
from typing import Any, Literal, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ZERO = Decimal("0")
USD = "USD"
AUTHORIZED_PORTFOLIOS = ("tradingagents", "ai-trading")


class IdempotencyConflict(ValueError):
    """An idempotency key was reused for different immutable event content."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class PriceType(StrEnum):
    EOD_CLOSE = "EOD_CLOSE"
    QUOTE = "QUOTE"


class Session(StrEnum):
    REGULAR = "REGULAR"
    CLOSED = "CLOSED"


class EventType(StrEnum):
    OPENING_CAPITAL = "OPENING_CAPITAL"
    BUY_FILL = "BUY_FILL"
    SELL_FILL = "SELL_FILL"
    MARK = "MARK"
    CANCEL = "CANCEL"


class OrderStatus(StrEnum):
    PROPOSED = "PROPOSED"
    REJECTED = "REJECTED"
    ACCEPTED = "ACCEPTED"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"


class Contract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Instrument(Contract):
    instrument_id: str = Field(pattern=r"^US:[A-Z][A-Z0-9.-]*$")
    ticker: str = Field(pattern=r"^[A-Z][A-Z0-9.-]*$")
    asset_type: Literal["EQUITY", "ETF"]
    venue: str
    quote_currency: str = USD
    quantity_scale: int = Field(default=0, ge=0, le=8)
    fractional_allowed: bool = False
    leveraged: bool = False
    inverse: bool = False

    @model_validator(mode="after")
    def valid_instrument(self) -> Self:
        if self.instrument_id != f"US:{self.ticker}":
            raise ValueError("instrument_id must be the canonical US:<TICKER> identifier")
        if self.quote_currency != USD:
            raise ValueError("P1 instruments must be USD-denominated")
        if self.leveraged or self.inverse:
            raise ValueError("leveraged and inverse instruments are prohibited")
        return self


class MarketSnapshot(Contract):
    instrument_id: str = Field(pattern=r"^US:[A-Z][A-Z0-9.-]*$")
    ticker: str = Field(pattern=r"^[A-Z][A-Z0-9.-]*$")
    provider: str = Field(min_length=1)
    price_type: PriceType
    currency: str = USD
    price: Decimal
    market_timestamp: datetime
    ingestion_timestamp: datetime
    publication_timestamp: datetime | None = None
    session: Session
    quality: str = Field(min_length=1)
    snapshot_id: UUID = Field(default_factory=uuid4)

    @field_validator("price")
    @classmethod
    def valid_price(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value <= ZERO:
            raise ValueError("price must be finite and positive")
        return value

    @field_validator("market_timestamp", "ingestion_timestamp", "publication_timestamp")
    @classmethod
    def utc_timestamps(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return value
        return require_utc(value)

    @model_validator(mode="after")
    def no_future_market_data(self) -> Self:
        if self.market_timestamp > self.ingestion_timestamp:
            raise ValueError("market timestamp cannot be after ingestion timestamp")
        if self.publication_timestamp is not None and self.publication_timestamp > self.ingestion_timestamp:
            raise ValueError("publication timestamp cannot be after ingestion timestamp")
        if self.price_type is PriceType.EOD_CLOSE and self.session is not Session.CLOSED:
            raise ValueError("EOD close snapshots must use the CLOSED session")
        if self.instrument_id != f"US:{self.ticker}" or self.currency != USD:
            raise ValueError("snapshot instrument and currency must be canonical USD values")
        return self


class ExperimentManifest(Contract):
    experiment_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    configuration_revision: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    created_at: datetime = Field(default_factory=utc_now)
    portfolio_ids: tuple[str, str] = ("tradingagents", "ai-trading")
    starting_capital_usd: Decimal = Decimal("1000")
    instruments: tuple[str, ...] = Field(min_length=1)
    data_policy: str = Field(min_length=1)

    @field_validator("created_at")
    @classmethod
    def manifest_time(cls, value: datetime) -> datetime:
        return require_utc(value)

    @field_validator("starting_capital_usd")
    @classmethod
    def exact_capital(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value != Decimal("1000"):
            raise ValueError("P1 requires exactly USD 1,000 starting capital")
        return value

    @model_validator(mode="after")
    def fixed_portfolios_and_universe(self) -> Self:
        if self.portfolio_ids != ("tradingagents", "ai-trading"):
            raise ValueError("P1 requires exactly the two named competitor portfolios")
        if len(set(self.instruments)) != len(self.instruments):
            raise ValueError("manifest instruments must be unique")
        if any(not instrument.startswith("US:") for instrument in self.instruments):
            raise ValueError("manifest instruments must use canonical US:<TICKER> IDs")
        return self


class TradeIntent(Contract):
    experiment_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    portfolio_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    strategy_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    instrument_id: str = Field(pattern=r"^US:[A-Z][A-Z0-9.-]*$")
    side: Side
    quantity: Decimal | None = None
    notional_usd: Decimal | None = None
    rationale: str = Field(min_length=1)
    model_revision: str = Field(min_length=1)
    decision_timestamp: datetime
    data_as_of: datetime
    stop_price: Decimal | None = None
    invalidation: str | None = None

    @field_validator("decision_timestamp", "data_as_of")
    @classmethod
    def intent_times(cls, value: datetime) -> datetime:
        return require_utc(value)

    @model_validator(mode="after")
    def explicit_size(self) -> Self:
        if self.side is Side.HOLD:
            if self.quantity is not None or self.notional_usd is not None:
                raise ValueError("HOLD cannot have a size")
        elif (self.quantity is None) == (self.notional_usd is None):
            raise ValueError("BUY/SELL must specify exactly one of quantity or notional")
        for name, value in (("quantity", self.quantity), ("notional_usd", self.notional_usd)):
            if value is not None and (not value.is_finite() or value <= ZERO):
                raise ValueError(f"{name} must be finite and positive")
        if self.data_as_of > self.decision_timestamp:
            raise ValueError("data_as_of cannot be after the decision timestamp")
        if self.stop_price is not None and (not self.stop_price.is_finite() or self.stop_price <= ZERO):
            raise ValueError("stop_price must be finite and positive")
        return self


class Order(Contract):
    order_id: UUID = Field(default_factory=uuid4)
    intent_id: UUID
    experiment_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    portfolio_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    instrument_id: str = Field(pattern=r"^US:[A-Z][A-Z0-9.-]*$")
    side: Side
    quantity: Decimal
    status: OrderStatus = OrderStatus.PROPOSED

    @field_validator("quantity")
    @classmethod
    def positive_quantity(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value <= ZERO:
            raise ValueError("order quantity must be finite and positive")
        return value

    @field_validator("side")
    @classmethod
    def executable_side(cls, value: Side) -> Side:
        if value is Side.HOLD:
            raise ValueError("HOLD cannot become an order")
        return value


class OrderEvent(Contract):
    order_id: UUID
    status: OrderStatus
    occurred_at: datetime
    filled_quantity: Decimal = ZERO
    reason: str | None = None

    @field_validator("occurred_at")
    @classmethod
    def order_event_time(cls, value: datetime) -> datetime:
        return require_utc(value)

    @field_validator("filled_quantity")
    @classmethod
    def valid_filled_quantity(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value < ZERO:
            raise ValueError("filled quantity cannot be negative")
        return value


class Posting(Contract):
    account: str = Field(min_length=1)
    debit: Decimal = ZERO
    credit: Decimal = ZERO

    @model_validator(mode="after")
    def nonnegative_single_sided(self) -> Self:
        if self.debit < ZERO or self.credit < ZERO or (self.debit and self.credit):
            raise ValueError("posting must be nonnegative and single-sided")
        if self.debit == ZERO and self.credit == ZERO:
            raise ValueError("posting cannot be empty")
        return self


class LedgerEvent(Contract):
    operation_id: UUID = Field(default_factory=uuid4)
    event_id: UUID = Field(default_factory=uuid4)
    portfolio_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    idempotency_key: str = Field(min_length=1)
    occurred_at: datetime
    currency: str = USD
    event_type: EventType
    postings: tuple[Posting, ...] = Field(min_length=2)
    instrument_id: str | None = Field(default=None, pattern=r"^US:[A-Z][A-Z0-9.-]*$")
    quantity: Decimal | None = None
    price: Decimal | None = None
    fee: Decimal = ZERO
    cost_basis: Decimal | None = None
    causation_id: UUID | None = None
    correlation_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("occurred_at")
    @classmethod
    def event_time(cls, value: datetime) -> datetime:
        return require_utc(value)

    @model_validator(mode="after")
    def balanced(self) -> Self:
        if self.portfolio_id not in AUTHORIZED_PORTFOLIOS:
            raise ValueError("portfolio is not authorized for the P1 experiment")
        if self.currency != USD:
            raise ValueError("P1 ledger events must be denominated in USD")
        if len({posting.account for posting in self.postings}) != len(self.postings):
            raise ValueError("ledger event may contain only one posting per account")
        debits = sum((posting.debit for posting in self.postings), ZERO)
        credits = sum((posting.credit for posting in self.postings), ZERO)
        if debits != credits:
            raise ValueError("ledger event postings must balance")
        if self.quantity is not None and self.quantity <= ZERO:
            raise ValueError("event quantity must be positive")
        if self.price is not None and (not self.price.is_finite() or self.price <= ZERO):
            raise ValueError("event price must be finite and positive")
        if self.fee < ZERO:
            raise ValueError("fee cannot be negative")
        if self.event_type not in {EventType.OPENING_CAPITAL, EventType.BUY_FILL, EventType.SELL_FILL}:
            raise ValueError(f"unsupported ledger event type: {self.event_type}")
        actual = {
            (posting.account, side): amount
            for posting in self.postings
            for side, amount in (("debit", posting.debit), ("credit", posting.credit))
            if amount != ZERO
        }
        if self.event_type is EventType.OPENING_CAPITAL:
            expected = {("cash", "debit"): Decimal("1000"), ("equity", "credit"): Decimal("1000")}
            if self.instrument_id or self.quantity or self.price or self.fee or actual != expected:
                raise ValueError("opening event must be exactly USD 1,000 cash against equity")
        elif self.event_type is EventType.BUY_FILL:
            if not self.instrument_id or self.quantity is None or self.price is None:
                raise ValueError("buy fill requires instrument, quantity, and price")
            gross = self.quantity * self.price
            expected = {
                (f"position:{self.instrument_id}", "debit"): gross,
                ("cash", "credit"): gross + self.fee,
            }
            if self.fee:
                expected[("fees", "debit")] = self.fee
            if actual != expected:
                raise ValueError("buy postings do not match gross cost, fee, and cash movement")
        elif self.event_type is EventType.SELL_FILL:
            if not self.instrument_id or self.quantity is None or self.price is None or self.cost_basis is None:
                raise ValueError("sell fill requires instrument, quantity, price, and cost_basis")
            if not self.cost_basis.is_finite() or self.cost_basis <= ZERO or self.fee > self.quantity * self.price:
                raise ValueError("sell cost basis and fee are economically invalid")
            gross = self.quantity * self.price
            realized = gross - self.cost_basis
            expected = {
                ("cash", "debit"): gross - self.fee,
                (f"position:{self.instrument_id}", "credit"): self.cost_basis,
            }
            if self.fee:
                expected[("fees", "debit")] = self.fee
            if realized > ZERO:
                expected[("realized_pnl", "credit")] = realized
            elif realized < ZERO:
                expected[("realized_pnl", "debit")] = -realized
            if actual != expected:
                raise ValueError("sell postings do not match cash, cost basis, fee, and realized P&L")
        return self

    def canonical(self) -> str:
        # event_id is a generated journal-row identity. Retries compare the
        # stable operation_id plus semantic payload, not a new event UUID.
        return json.dumps(
            self.model_dump(mode="json", round_trip=True, exclude={"event_id"}),
            separators=(",", ":"),
            sort_keys=True,
        )
