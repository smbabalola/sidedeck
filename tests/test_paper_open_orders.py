import pytest

from sidedeck.infrastructure.alpaca_paper import AlpacaPaperBinding
from sidedeck.infrastructure.alpaca_readonly import AlpacaReadOnly


def test_no_open_orders_fixture():
    paths = []
    def get(path):
        paths.append(path)
        return []
    assert AlpacaReadOnly(AlpacaPaperBinding(), get).open_order_count() == 0
    assert paths == ["/v2/orders?status=open&limit=500"]


def test_outstanding_orders_are_detected():
    client = AlpacaReadOnly(AlpacaPaperBinding(), lambda path: [{"id": "synthetic-order"}])
    assert client.open_order_count() == 1


def test_capped_page_fails_closed():
    client = AlpacaReadOnly(AlpacaPaperBinding(), lambda path: [{"id": str(n)} for n in range(500)])
    with pytest.raises(ValueError, match="pagination"):
        client.open_order_count()


def test_bad_order_payload_fails_closed():
    client = AlpacaReadOnly(AlpacaPaperBinding(), lambda path: [{"unexpected": "data"}])
    with pytest.raises(ValueError):
        client.open_order_count()
