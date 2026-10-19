from decimal import Decimal

from sidedeck.application.paper_readiness import inspect_paper_readiness
from sidedeck.domain.accounting import PortfolioState
from sidedeck.infrastructure.alpaca_paper import AlpacaPaperBinding
from sidedeck.infrastructure.alpaca_readonly import AlpacaReadOnly


def test_integrated_paper_readiness_with_order_free_synthetic_account():
    calls = []
    def fixture(path):
        calls.append(path)
        if path == "/v2/account":
            return {"id": "fake-paper", "currency": "USD", "cash": "2000",
                    "equity": "2000", "status": "ACTIVE"}
        if path == "/v2/positions":
            return []
        if path == "/v2/orders?status=open&limit=500":
            return []
        raise AssertionError("unexpected endpoint")

    state = {
        "tradingagents": PortfolioState("tradingagents", Decimal("1000")),
        "ai-trading": PortfolioState("ai-trading", Decimal("1000")),
    }
    result = inspect_paper_readiness(
        AlpacaReadOnly(AlpacaPaperBinding(), fixture), state,
        expected_account_id="fake-paper", dedicated_account=True,
    )
    assert result.ready_for_review
    assert calls == ["/v2/account", "/v2/positions", "/v2/orders?status=open&limit=500"]


def test_open_orders_fail_entire_readiness_gate():
    def fixture(path):
        if path == "/v2/account":
            return {"id": "fake-paper", "currency": "USD", "cash": "2000",
                    "equity": "2000", "status": "ACTIVE"}
        if path == "/v2/positions":
            return []
        return [{"id": "outstanding"}]
    state = {
        "tradingagents": PortfolioState("tradingagents", Decimal("1000")),
        "ai-trading": PortfolioState("ai-trading", Decimal("1000")),
    }
    result = inspect_paper_readiness(
        AlpacaReadOnly(AlpacaPaperBinding(), fixture), state,
        expected_account_id="fake-paper", dedicated_account=True,
    )
    assert not result.ready_for_review
    assert result.reason == "outstanding_open_orders"
