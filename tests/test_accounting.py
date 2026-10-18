from datetime import datetime, timezone
from decimal import Decimal

import pytest

from sidedeck.application.foundation import initialise_two_portfolios
from sidedeck.domain.accounting import fill_event
from sidedeck.domain.contracts import EventType, ExperimentManifest, MarketSnapshot, PriceType, Session

AT = datetime(2026, 1, 2, 21, 0, tzinfo=timezone.utc)


def manifest() -> ExperimentManifest:
    return ExperimentManifest(
        experiment_id="EXP-001",
        configuration_revision="r1",
        instruments=("US:AAPL",),
        data_policy="as-of fixture only",
        created_at=AT,
    )


def mark(price: str) -> MarketSnapshot:
    return MarketSnapshot(
        instrument_id="US:AAPL", ticker="AAPL", provider="fixture",
        price_type=PriceType.EOD_CLOSE, price=Decimal(price),
        market_timestamp=AT, ingestion_timestamp=AT, session=Session.CLOSED,
        quality="deterministic_fixture",
    )


def test_two_portfolios_are_isolated_and_start_at_one_thousand() -> None:
    ledger = initialise_two_portfolios(manifest(), AT)
    states = ledger.rebuild()
    assert set(states) == {"tradingagents", "ai-trading"}
    assert states["tradingagents"].cash == Decimal("1000")
    assert states["ai-trading"].cash == Decimal("1000")
    ledger.append(fill_event("tradingagents", "buy-1", EventType.BUY_FILL, "US:AAPL", Decimal("2"), Decimal("100"), AT, Decimal("1")))
    assert ledger.replay("tradingagents").cash == Decimal("799")
    assert ledger.replay("ai-trading").cash == Decimal("1000")


def test_deterministic_replay_fills_fees_nav_and_realized_pnl() -> None:
    ledger = initialise_two_portfolios(manifest(), AT)
    ledger.append(fill_event("tradingagents", "buy-1", EventType.BUY_FILL, "US:AAPL", Decimal("2"), Decimal("100"), AT, Decimal("1")))
    ledger.append(fill_event("tradingagents", "sell-1", EventType.SELL_FILL, "US:AAPL", Decimal("1"), Decimal("120"), AT, Decimal("1")))
    state = ledger.replay("tradingagents")
    assert state.cash == Decimal("918")
    assert state.positions["US:AAPL"].quantity == Decimal("1")
    assert state.realized_gross == Decimal("20")
    assert state.realized_net == Decimal("18")
    assert state.nav({"US:AAPL": mark("110")}) == Decimal("1028")
    assert ledger.replay("tradingagents").nav({"US:AAPL": mark("110")}) == Decimal("1028")


def test_duplicate_event_is_idempotent_and_oversell_is_rejected() -> None:
    ledger = initialise_two_portfolios(manifest(), AT)
    buy = fill_event("tradingagents", "buy-1", EventType.BUY_FILL, "US:AAPL", Decimal("1"), Decimal("100"), AT)
    assert ledger.append(buy) is True
    assert ledger.append(buy) is False
    with pytest.raises(ValueError, match="sell more"):
        ledger.append(fill_event("tradingagents", "sell-2", EventType.SELL_FILL, "US:AAPL", Decimal("2"), Decimal("100"), AT))


def test_invalid_cash_and_prohibited_trade_inputs_fail_closed() -> None:
    ledger = initialise_two_portfolios(manifest(), AT)
    with pytest.raises(ValueError):
        ledger.append(fill_event("tradingagents", "buy-too-much", EventType.BUY_FILL, "US:AAPL", Decimal("11"), Decimal("100"), AT))
    with pytest.raises(ValueError):
        fill_event("tradingagents", "bad", EventType.BUY_FILL, "US:BTC", Decimal("1"), Decimal("1"), AT)
