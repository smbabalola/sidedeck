from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from sidedeck.domain.contracts import (
    EventType,
    ExperimentManifest,
    LedgerEvent,
    MarketSnapshot,
    Order,
    Posting,
    PriceType,
    Session,
    Side,
    TradeIntent,
)
from sidedeck.domain.accounting import fill_event
from sidedeck.domain.instruments import get_instrument, validate_quantity
from sidedeck.domain.market import validate_snapshot

UTC = timezone.utc
AT = datetime(2026, 1, 2, 21, 0, tzinfo=UTC)


def snapshot(price: str = "100", market_time: datetime = AT) -> MarketSnapshot:
    return MarketSnapshot(
        instrument_id="US:AAPL",
        ticker="AAPL",
        provider="fixture",
        price_type=PriceType.EOD_CLOSE,
        price=Decimal(price),
        market_timestamp=market_time,
        ingestion_timestamp=max(AT, market_time),
        session=Session.CLOSED,
        quality="deterministic_fixture",
    )


def test_manifest_requires_two_thousand_dollar_total_and_two_ids() -> None:
    manifest = ExperimentManifest(
        experiment_id="EXP-001",
        configuration_revision="r1",
        instruments=("US:AAPL", "US:SPY"),
        data_policy="as-of fixture only",
    )
    assert manifest.portfolio_ids == ("tradingagents", "ai-trading")
    assert manifest.starting_capital_usd == Decimal("1000")
    with pytest.raises(ValidationError):
        ExperimentManifest(
            experiment_id="EXP-001", configuration_revision="r1",
            instruments=("US:AAPL",), data_policy="fixture",
            starting_capital_usd=Decimal("999"),
        )


@pytest.mark.parametrize("price", ["0", "-1", "NaN", "Infinity"])
def test_invalid_prices_fail_closed(price: str) -> None:
    with pytest.raises(ValidationError):
        snapshot(price)


def test_market_snapshot_rejects_future_and_stale_data() -> None:
    with pytest.raises(ValueError, match="future"):
        validate_snapshot(snapshot(market_time=AT + timedelta(minutes=1)), AT, timedelta(days=1))
    with pytest.raises(ValueError, match="stale"):
        validate_snapshot(snapshot(market_time=AT - timedelta(days=2)), AT, timedelta(days=1))
    with pytest.raises(ValueError, match="future"):
        validate_snapshot(snapshot(market_time=AT,).model_copy(update={"ingestion_timestamp": AT + timedelta(minutes=1)}), AT, timedelta(days=1))


def test_trade_intent_is_not_an_order_and_hold_has_no_size() -> None:
    intent = TradeIntent(
        experiment_id="EXP-001",
        portfolio_id="tradingagents",
        strategy_id="fixture",
        instrument_id="US:AAPL",
        side=Side.HOLD,
        rationale="No change",
        model_revision="fixture-1",
        decision_timestamp=AT,
        data_as_of=AT,
    )
    assert intent.side is Side.HOLD
    with pytest.raises(ValidationError):
        TradeIntent(
            experiment_id="EXP-001", portfolio_id="tradingagents", strategy_id="fixture",
            instrument_id="US:AAPL", side=Side.HOLD, quantity=Decimal("1"),
            rationale="No change", model_revision="fixture-1",
            decision_timestamp=AT, data_as_of=AT,
        )


def test_instrument_allowlist_and_precision() -> None:
    instrument = get_instrument("AAPL")
    assert instrument.asset_type == "EQUITY"
    validate_quantity(instrument, Decimal("2"))
    with pytest.raises(ValueError):
        get_instrument("BTC")
    with pytest.raises(ValueError):
        validate_quantity(instrument, Decimal("0.5"))


def test_instrument_and_snapshot_currency_identity_fail_closed() -> None:
    with pytest.raises(ValidationError):
        MarketSnapshot(
            instrument_id="US:MSFT", ticker="AAPL", provider="fixture",
            price_type=PriceType.EOD_CLOSE, price=Decimal("100"),
            market_timestamp=AT, ingestion_timestamp=AT, session=Session.CLOSED,
            quality="fixture",
        )
    with pytest.raises(ValidationError):
        MarketSnapshot.model_validate({**snapshot().model_dump(), "currency": "EUR"})


def test_order_rejects_hold_and_event_rejects_unsupported_or_economic_mismatch() -> None:
    with pytest.raises(ValidationError):
        Order(
            intent_id="00000000-0000-0000-0000-000000000001",
            experiment_id="EXP-001", portfolio_id="tradingagents", instrument_id="US:AAPL",
            side=Side.HOLD, quantity=Decimal("1"),
        )
    with pytest.raises(ValidationError):
        LedgerEvent(
            portfolio_id="tradingagents", idempotency_key="bad-opening", occurred_at=AT,
            event_type=EventType.OPENING_CAPITAL,
            postings=(Posting(account="cash", debit=Decimal("999")), Posting(account="equity", credit=Decimal("999"))),
        )
    with pytest.raises(ValidationError):
        LedgerEvent(
            portfolio_id="tradingagents", idempotency_key="bad-type", occurred_at=AT,
            event_type=EventType.MARK,
            postings=(Posting(account="cash", debit=Decimal("1")), Posting(account="equity", credit=Decimal("1"))),
        )


def test_fill_postings_match_cash_cost_basis_fees_and_realized_pnl() -> None:
    buy = fill_event("tradingagents", "buy", EventType.BUY_FILL, "US:AAPL", Decimal("2"), Decimal("100"), AT, Decimal("1"))
    assert {(p.account, p.debit, p.credit) for p in buy.postings} == {
        ("position:US:AAPL", Decimal("200"), Decimal("0")),
        ("fees", Decimal("1"), Decimal("0")),
        ("cash", Decimal("0"), Decimal("201")),
    }
    sell = fill_event("tradingagents", "sell", EventType.SELL_FILL, "US:AAPL", Decimal("1"), Decimal("120"), AT, Decimal("1"), Decimal("100"))
    assert {(p.account, p.debit, p.credit) for p in sell.postings} == {
        ("cash", Decimal("119"), Decimal("0")),
        ("fees", Decimal("1"), Decimal("0")),
        ("position:US:AAPL", Decimal("0"), Decimal("100")),
        ("realized_pnl", Decimal("0"), Decimal("20")),
    }
    malformed = buy.model_dump(mode="python")
    malformed["postings"] = (
        Posting(account="position:US:AAPL", debit=Decimal("200")),
        Posting(account="cash", credit=Decimal("200")),
    )
    with pytest.raises(ValidationError):
        LedgerEvent.model_validate(malformed)
