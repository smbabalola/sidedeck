from decimal import Decimal

import pytest

from sidedeck.application.reconciliation import reconcile_positions
from sidedeck.domain.accounting import PortfolioState, Position
from sidedeck.infrastructure.alpaca_readonly import PaperPosition


def setup():
    a = PortfolioState(portfolio_id="tradingagents", cash=Decimal("900"),
                       positions={"US:AAPL": Position(Decimal("1"), Decimal("100"))})
    b = PortfolioState(portfolio_id="ai-trading", cash=Decimal("800"),
                       positions={"US:AAPL": Position(Decimal("2"), Decimal("200"))})
    return {"tradingagents": a, "ai-trading": b}


def test_combines_two_internal_portfolios():
    report = reconcile_positions(setup(), (PaperPosition("AAPL", Decimal("3"), Decimal("300")),))
    assert report.matched and not report.differences


def test_reports_broker_and_internal_mismatch():
    report = reconcile_positions(setup(), (PaperPosition("AAPL", Decimal("2"), Decimal("200")),))
    assert not report.matched
    assert report.differences[0].internal_quantity == Decimal("3")
    assert report.differences[0].broker_quantity == Decimal("2")


def test_unknown_broker_holding_blocks_exact_reconciliation():
    report = reconcile_positions(setup(), (
        PaperPosition("AAPL", Decimal("3"), Decimal("300")),
        PaperPosition("MSFT", Decimal("1"), Decimal("100")),
    ))
    assert not report.matched
    assert report.differences[0].symbol == "MSFT"


def test_missing_portfolio_fails_closed():
    with pytest.raises(ValueError):
        reconcile_positions({"tradingagents": setup()["tradingagents"]}, ())
