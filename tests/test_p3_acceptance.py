from decimal import Decimal

from sidedeck.application.p3_acceptance import assess_p3
from sidedeck.domain.accounting import PortfolioState
from sidedeck.infrastructure.alpaca_paper import AlpacaPaperBinding
from sidedeck.infrastructure.alpaca_readonly import AlpacaReadOnly


def test_full_synthetic_acceptance_gate():
    calls = []
    def read(path):
        calls.append(path)
        return {
            "/v2/account": {"id": "synthetic-paper", "currency": "USD", "cash": "2000",
                            "equity": "2000", "status": "ACTIVE"},
            "/v2/positions": [],
            "/v2/orders?status=open&limit=500": [],
        }[path]
    states = {
        "tradingagents": PortfolioState("tradingagents", Decimal("1000")),
        "ai-trading": PortfolioState("ai-trading", Decimal("1000")),
    }
    decision = assess_p3(AlpacaReadOnly(AlpacaPaperBinding(), read), states,
                         expected_account_id="synthetic-paper", dedicated_account=True)
    assert decision.approved
    assert len(calls) == 3


def test_unattributed_broker_cash_blocks_gate():
    def read(path):
        return {
            "/v2/account": {"id": "synthetic-paper", "currency": "USD", "cash": "3000",
                            "equity": "3000", "status": "ACTIVE"},
            "/v2/positions": [],
            "/v2/orders?status=open&limit=500": [],
        }[path]
    states = {
        "tradingagents": PortfolioState("tradingagents", Decimal("1000")),
        "ai-trading": PortfolioState("ai-trading", Decimal("1000")),
    }
    decision = assess_p3(AlpacaReadOnly(AlpacaPaperBinding(), read), states,
                         expected_account_id="synthetic-paper", dedicated_account=True)
    assert not decision.approved
    assert decision.reason == "cash_mismatch_or_unattributed_funds"
