from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from sidedeck.domain.contracts import (
    ExperimentManifest,
    MarketSnapshot,
    PriceType,
    Session,
    Side,
    TradeIntent,
)
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
