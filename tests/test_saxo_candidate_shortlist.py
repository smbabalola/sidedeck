from sidedeck.application.saxo_candidate_shortlist import TICKERS, evaluate_candidate
from sidedeck.application.saxo_instruments import StockCandidate


def test_fixed_universe_does_not_include_crypto():
    assert TICKERS == ("F", "SOFI", "PLTR", "PFE", "T", "INTC")


def test_nasdaq_stock_detail_candidate():
    c = StockCandidate(42, "F:xnas", "Stock", "Example")
    base = {"Uic": 42, "Symbol": "F:xnas", "AssetType": "Stock",
            "CurrencyCode": "USD", "TradingStatus": "Tradable",
            "TradableOn": ["synthetic"]}
    assert evaluate_candidate(c, base) == (True, "detail_candidate_only")
    assert evaluate_candidate(c, {**base, "CurrencyCode": "EUR"})[0] is False
    assert evaluate_candidate(c, {**base, "Uic": 43})[0] is False
    assert evaluate_candidate(c, {**base, "TradingStatus": "NotTradable"})[0] is False
    assert evaluate_candidate(c, {**base, "TradableOn": []})[0] is False
    assert evaluate_candidate(StockCandidate(42, "F:xmil", "Stock", "Example"), base)[0] is False
