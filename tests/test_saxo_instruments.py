import pytest

from sidedeck.application.saxo_instruments import parse_stock_candidates, stock_lookup_path
from sidedeck.infrastructure.saxo_account_scope import SaxoAccountScope
from sidedeck.infrastructure.saxo_sim import SaxoSimClient


def test_bounded_account_scoped_search_path():
    scope = SaxoAccountScope("22866064", "synthetic==", "client==")
    path = stock_lookup_path(scope, "AAPL")
    assert path == "/ref/v1/instruments?AccountKey=synthetic%3D%3D&AssetTypes=Stock&Keywords=AAPL&%24top=20"
    with pytest.raises(ValueError):
        stock_lookup_path(scope, "AAPL&Orders=1")


def test_stock_candidate_filters_nonstock_and_similar_symbols():
    data = {"Data": [
        {"AssetType": "Stock", "Identifier": 211, "Symbol": "AAPL:xnas",
         "Description": "Apple Inc"},
        {"AssetType": "CfdOnStock", "Identifier": 212, "Symbol": "AAPL:xnas"},
        {"AssetType": "Stock", "Identifier": 213, "Symbol": "AA:xnas"},
    ]}
    result = parse_stock_candidates(data, ticker="AAPL")
    assert len(result) == 1
    assert result[0].uic == 211


def test_pagination_fails_closed():
    with pytest.raises(ValueError, match="incomplete"):
        parse_stock_candidates({"Data": [], "__next": "next"}, ticker="AAPL")
    with pytest.raises(ValueError, match="truncated"):
        parse_stock_candidates({"Data": [], "__count": 21}, ticker="AAPL")


def test_disallow_order_url_and_unbounded_search(monkeypatch):
    monkeypatch.delenv("SAXO_SIM_ACCESS_TOKEN", raising=False)
    client = SaxoSimClient()
    for path in ("/trade/v2/orders", "/trade/v2/orders/precheck",
                 "/ref/v1/instruments?Keywords=AAPL",
                 "/ref/v1/instruments?AccountKey=a&AssetTypes=Stock&Keywords=AAPL&%24top=21"):
        with pytest.raises(PermissionError):
            client.get(path)
