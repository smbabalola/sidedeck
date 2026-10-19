from decimal import Decimal

from sidedeck.application.paper_snapshot import assess_paper_snapshot
from sidedeck.domain.accounting import PortfolioState
from sidedeck.infrastructure.alpaca_paper import AlpacaPaperBinding
from sidedeck.infrastructure.alpaca_readonly import AlpacaReadOnly


def setup(cash="2000", positions=None):
    def fixture(path):
        if path == "/v2/account":
            return {"id": "synthetic-sidedeck", "currency": "USD", "cash": cash,
                    "equity": cash, "status": "ACTIVE"}
        assert path == "/v2/positions"
        return [] if positions is None else positions
    portfolios = {
        "tradingagents": PortfolioState("tradingagents", Decimal("1000")),
        "ai-trading": PortfolioState("ai-trading", Decimal("1000")),
    }
    return AlpacaReadOnly(AlpacaPaperBinding(), fixture), portfolios


def test_read_only_consistent_dedicated_account():
    client, portfolios = setup()
    result = assess_paper_snapshot(
        client, portfolios, expected_account_id="synthetic-sidedeck",
        dedicated_account=True,
    )
    assert result.safe_to_attribute
    assert result.reason == "read_only_snapshot_consistent"


def test_unattributed_cash_must_block_attribution():
    client, portfolios = setup(cash="2500")
    result = assess_paper_snapshot(
        client, portfolios, expected_account_id="synthetic-sidedeck",
        dedicated_account=True,
    )
    assert not result.safe_to_attribute
    assert result.reason == "cash_mismatch_or_unattributed_funds"


def test_dedication_not_inferred_from_balances():
    client, portfolios = setup()
    result = assess_paper_snapshot(client, portfolios, expected_account_id="synthetic-sidedeck")
    assert not result.safe_to_attribute
    assert result.reason == "account_dedication_unverified"


def test_wrong_account_blocks_even_when_balances_match():
    client, portfolios = setup()
    result = assess_paper_snapshot(
        client, portfolios, expected_account_id="incorrect", dedicated_account=True
    )
    assert not result.safe_to_attribute
    assert result.reason == "account_identity_mismatch"
