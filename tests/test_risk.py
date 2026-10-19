from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from sidedeck.application.risk import RiskLimits, screen_proposal
from sidedeck.domain.accounting import PortfolioState, Position
from sidedeck.domain.contracts import (
    ExperimentManifest, MarketSnapshot, PriceType, Session, Side, TradeIntent,
)

NOW = datetime(2026, 10, 19, 18, tzinfo=timezone.utc)


def setup_case(side=Side.BUY, quantity="1", cash="1000", held="0"):
    manifest = ExperimentManifest(
        experiment_id="risk-test", configuration_revision="v1",
        created_at=NOW - timedelta(days=1), instruments=("US:AAPL",),
        data_policy="synthetic-test-only",
    )
    snapshot = MarketSnapshot(
        instrument_id="US:AAPL", ticker="AAPL", provider="fixture",
        price_type=PriceType.EOD_CLOSE, price=Decimal("100"),
        market_timestamp=NOW - timedelta(hours=1),
        ingestion_timestamp=NOW - timedelta(minutes=1),
        session=Session.CLOSED, quality="synthetic-test-only",
    )
    intent = TradeIntent(
        experiment_id="risk-test", portfolio_id="tradingagents", strategy_id="unit-test",
        instrument_id="US:AAPL", side=side,
        quantity=Decimal(quantity) if side is not Side.HOLD else None,
        rationale="test", model_revision="v1", decision_timestamp=NOW,
        data_as_of=snapshot.market_timestamp,
    )
    state = PortfolioState(portfolio_id="tradingagents", cash=Decimal(cash))
    if Decimal(held):
        state.positions["US:AAPL"] = Position(
            quantity=Decimal(held), cost_basis=Decimal(held) * Decimal("100")
        )
    return manifest, snapshot, intent, state


def screen(case, limits=RiskLimits()):
    m, s, i, p = case
    return screen_proposal(
        i, m, s, p, max_market_age=timedelta(hours=2),
        marks={"US:AAPL": s}, limits=limits,
    )


def test_small_buy_allowed_but_not_executed():
    decision = screen(setup_case())
    assert decision.accepted and decision.reason == "buy_proposal_only"
    assert decision.proposed_quantity == Decimal("1")


def test_concentration_limit_rejects_large_buy():
    assert screen(setup_case(quantity="3")).reason == "position_concentration_limit"


def test_cash_restriction_rejects_overspend():
    assert screen(setup_case(quantity="11")).reason == "insufficient_cash"


def test_existing_position_counts_toward_concentration():
    assert screen(setup_case(quantity="1", cash="800", held="2")).reason == "position_concentration_limit"


def test_sell_must_be_fully_owned():
    assert screen(setup_case(side=Side.SELL, quantity="2", held="1")).reason == "insufficient_position"


def test_sell_with_existing_position_allowed():
    decision = screen(setup_case(side=Side.SELL, quantity="1", cash="900", held="1"))
    assert decision.accepted and decision.reason == "sell_proposal_only"


def test_cross_portfolio_state_rejected():
    case = setup_case()
    case[-1].portfolio_id = "ai-trading"
    assert screen(case).reason == "portfolio_state_mismatch"


def test_hold_produces_no_order():
    assert screen(setup_case(side=Side.HOLD)).reason == "hold_no_order"


def test_invalid_limits_fail_closed():
    with pytest.raises(ValueError):
        RiskLimits(max_new_position_fraction=Decimal("NaN"))


def test_unavailable_mark_rejects_portfolio_valuation():
    m, s, i, state = setup_case()
    state.positions["US:MSFT"] = Position(Decimal("1"), Decimal("200"))
    decision = screen_proposal(
        i, m, s, state, max_market_age=timedelta(hours=2), marks={}
    )
    assert decision.reason == "unavailable_portfolio_valuation"
