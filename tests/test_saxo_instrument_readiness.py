import pytest

from sidedeck.application.saxo_instrument_readiness import (
    assess_detail, inspect_price, detail_path, price_path,
)
from sidedeck.infrastructure.saxo_account_scope import SaxoAccountScope
from sidedeck.infrastructure.saxo_sim import SaxoSimClient


def test_exact_sim_stock_identity_and_currency():
    result = assess_detail({"Uic": 211, "AssetType": "Stock", "Symbol": "AAPL:xnas",
                            "CurrencyCode": "USD", "TradingStatus": "Tradable",
                            "TradableOn": ["test-account"]}, expected_uic=211)
    assert result.tradable
    assert result.reason == "detail_candidate_only"


@pytest.mark.parametrize("changes", [
    {"Uic": 15777171}, {"AssetType": "CfdOnStock"}, {"Symbol": "AAPL:xmil"},
    {"CurrencyCode": "EUR"}, {"TradingStatus": "NotTradable"},
])
def test_detail_must_not_fail_open(changes):
    base = {"Uic": 211, "AssetType": "Stock", "Symbol": "AAPL:xnas",
            "CurrencyCode": "USD", "TradingStatus": "Tradable",
            "TradableOn": ["test-account"]}
    base.update(changes)
    assert not assess_detail(base, expected_uic=211).tradable


def test_quote_is_indicative_not_executable():
    assert inspect_price({"Quote": {"Bid": 100, "Ask": 101}}) == (
        "indicative_bid_ask_observed_freshness_unverified"
    )
    assert inspect_price({}) == "quote_not_available"
    assert inspect_price({"Quote": {"Bid": 100}}) == "bid_ask_not_available"
    with pytest.raises(ValueError):
        inspect_price({"Quote": {"Bid": 102, "Ask": 101}})


def test_only_read_only_paths(monkeypatch):
    scope = SaxoAccountScope("22866064", "fake==", "client==")
    assert "details/211/Stock" in detail_path(scope, 211)
    assert "Uic=211" in price_path(scope, 211)
    with pytest.raises(ValueError):
        detail_path(scope, 0)
    monkeypatch.delenv("SAXO_SIM_ACCESS_TOKEN", raising=False)
    with pytest.raises(PermissionError):
        SaxoSimClient().get("/trade/v2/orders")
