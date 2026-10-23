"""PAPER order POST contract construction: no HTTP, no credentials, no writes."""

from dataclasses import replace
from decimal import Decimal
import json

import pytest

from sidedeck.domain.paper_desk import PaperDeskError
from sidedeck.domain.paper_post_contract import (
    build_paper_post_preview, encode_paper_post_request,
)
from tests.test_paper_submission import setup


def test_only_hardcoded_paper_host_limit_day_body_and_no_credentials(tmp_path):
    db, draft, *_ = setup(tmp_path)
    preview = build_paper_post_preview(draft)
    assert preview.url == "https://paper-api.alpaca.markets/v2/orders"
    assert preview.method == "POST"
    assert preview.owner_authorized is False
    assert preview.network_enabled is False
    assert preview.body == {
        "symbol": "AAPL",
        "side": "buy",
        "qty": "1",
        "type": "limit",
        "time_in_force": "day",
        "limit_price": "100.00",
        "extended_hours": False,
        "client_order_id": draft.client_order_id,
    }
    request = encode_paper_post_request(draft)
    assert request.full_url == preview.url
    assert request.get_method() == "POST"
    assert json.loads(request.data or b"{}") == preview.body
    assert "APCA-API-KEY-ID" not in request.headers
    assert "APCA-API-SECRET-KEY" not in request.headers
    assert db.kill_switch_engaged is True


@pytest.mark.parametrize("changes", [
    {"symbol": "BTCUSD"},
    {"side": "short"},
    {"key_slot": "ALPACA_API_KEY2"},
    {"client_order_id": "UNOWNED"},
    {"quantity": Decimal("0.1")},
    {"quantity": Decimal("0")},
    {"quantity": Decimal("NaN")},
    {"limit_price": Decimal("0")},
    {"limit_price": Decimal("NaN")},
    {"limit_price": Decimal("100.001")},
    {"quantity": Decimal("20")},
    {"submission_enabled": True},
])
def test_paper_post_preview_rejects_invalid_or_overallocated_orders(tmp_path, changes):
    _, draft, *_ = setup(tmp_path)
    with pytest.raises(PaperDeskError):
        build_paper_post_preview(replace(draft, **changes))


def test_no_live_network_apis_in_module():
    import sidedeck.domain.paper_post_contract as contract
    assert not hasattr(contract, "submit")
    assert not hasattr(contract, "open_url")
    assert not hasattr(contract, "urlopen")
    assert not hasattr(contract, "AlpacaLiveTradingTransport")
