from decimal import Decimal

import pytest

from sidedeck.infrastructure.alpaca_paper import AlpacaPaperBinding
from sidedeck.infrastructure.alpaca_readonly import AlpacaReadOnly


def test_account_and_positions_from_injected_fixture():
    calls = []
    def transport(path):
        calls.append(path)
        if path == "/v2/account":
            return {"id": "synthetic-account", "currency": "USD",
                    "cash": "950.00", "equity": "1002.50", "status": "ACTIVE"}
        if path == "/v2/positions":
            return [{"symbol": "AAPL", "qty": "1", "market_value": "52.50"}]
        raise AssertionError("unauthorized endpoint")
    client = AlpacaReadOnly(AlpacaPaperBinding(), transport)
    assert client.account().equity == Decimal("1002.50")
    assert client.positions()[0].symbol == "AAPL"
    assert calls == ["/v2/account", "/v2/positions"]


def test_rejects_malformed_broker_payload():
    client = AlpacaReadOnly(AlpacaPaperBinding(), lambda path: {
        "id": "fake", "currency": "USD", "cash": "NaN",
        "equity": "1000", "status": "ACTIVE",
    })
    with pytest.raises(ValueError):
        client.account()


def test_rejects_duplicate_positions():
    client = AlpacaReadOnly(AlpacaPaperBinding(), lambda path: [
        {"symbol": "AAPL", "qty": "1", "market_value": "10"},
        {"symbol": "AAPL", "qty": "1", "market_value": "10"},
    ])
    with pytest.raises(ValueError):
        client.positions()
