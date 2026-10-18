from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Any, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ZERO = Decimal("0")
USD = "USD"


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
    instrument_id: str = Field(min_length=1)
    ticker: str = Field(min_length=1)
    asset_type: str
    venue: str
    quote_currency: str = USD
    quantity_scale: int = Field(default=0, ge=0, le=8)
    fractional_allowed: bool = False
    leveraged: bool = False
    inverse: bool = False


class MarketSnapshot(Contract):
    instrument_id: str = Field(min_length=1)
    ticker: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    price_type: PriceType
    currency: str = USD
    price: Decimal
    market_timestamp: datetime
    ingestion_timestamp: datetime
    session: Session
    quality: str = Field(min_length=1)
    snapshot_id: UUID = Field(default_factory=uuid4)

    @field_validator("price")
    @classmethod
    def valid_price(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value <= ZERO:
            raise ValueError("price must be finite and positive")
        return value

    @field_validator("market_timestamp", "ingestion_timestamp")
    @classmethod
    def utc_timestamps(cls, value: datetime) -> datetime:
        return require_utc(value)

    @model_validator(mode="after")
    def no_future_market_data(self) -> Self:
        if self.market_timestamp > self.ingestion_timestamp:
            raise ValueError("market timestamp cannot be after ingestion timestamp")
        if self.price_type is PriceType.EOD_CLOSE and self.session is not Session.CLOSED:
            raise ValueError("EOD close snapshots must use the CLOSED session")
        return self


class ExperimentManifest(Contract):
    experiment_id: str = Field(min_length=1)
    configuration_revision: str = Field(min_length=1)
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
        if value != Decimal("1000"):
            raise ValueError("P1 requires exactly USD 1,000 starting capital")
        return value


class TradeIntent(Contract):
    experiment_id: str = Field(min_length=1)
    portfolio_id: str = Field(min_length=1)
    strategy_id: str = Field(min_length=1)
    instrument_id: str = Field(min_length=1)
    side: Side
    quantity: Decimal | None = None
    notional_usd: Decimal | None = None
    rationale: str = Field(min_length=1)
    model_revision: str = Field(min_length=1)
    decision_timestamp: datetime
    data_as_of: datetime

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
        return self


class Order(Contract):
    order_id: UUID = Field(default_factory=uuid4)
    intent_id: UUID
    experiment_id: str = Field(min_length=1)
    portfolio_id: str = Field(min_length=1)
    instrument_id: str = Field(min_length=1)
    side: Side
    quantity: Decimal
    status: OrderStatus = OrderStatus.PROPOSED

    @field_validator("quantity")
    @classmethod
    def positive_quantity(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value <= ZERO:
            raise ValueError("order quantity must be finite and positive")
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
    event_id: UUID = Field(default_factory=uuid4)
    portfolio_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    occurred_at: datetime
    currency: str = USD
    event_type: EventType
    postings: tuple[Posting, ...] = Field(min_length=2)
    instrument_id: str | None = None
    quantity: Decimal | None = None
    price: Decimal | None = None
    fee: Decimal = ZERO
    causation_id: UUID | None = None
    correlation_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("occurred_at")
    @classmethod
    def event_time(cls, value: datetime) -> datetime:
        return require_utc(value)

    @model_validator(mode="after")
    def balanced(self) -> Self:
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
        return self

    def canonical(self) -> str:
        return self.model_dump_json(round_trip=True)
