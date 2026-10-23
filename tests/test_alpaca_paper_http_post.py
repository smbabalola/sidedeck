"""Hard disabled Alpaca PAPER HTTP writer, contract-tested with fake opener."""

from dataclasses import replace
from datetime import timedelta
import io
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit

import pytest

from sidedeck.domain import alpaca_paper_http_post as api
from sidedeck.domain.paper_desk import PaperDeskError
from tests.test_paper_submission import NOW, setup


class FakeResponse:
    status = 200
    def __init__(self, body):
        self._data = body
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return None
    def read(self, size):
        return self._data


def permit(draft):
    return api.PaperOrderPermit(
        client_order_id=draft.client_order_id, key_slot=draft.key_slot,
        expires_at=NOW + timedelta(seconds=30),
        verified_account_slot=True, owner_confirmed=True,
    )


def test_product_transport_blocks_all_paper_writes_before_opening_http(tmp_path, monkeypatch):
    _, draft, *_ = setup(tmp_path)
    monkeypatch.setattr(api, "NETWORK_PAPER_WRITES_ENABLED", False)
    monkeypatch.setattr(api, "build_opener", lambda *_: pytest.fail("unexpected HTTP"))
    client = api.AlpacaPaperPostTransport(api.RestrictedPaperAuth("FAKE_KEY", "FAKE_SECRET"))
    with pytest.raises(PaperDeskError, match="disabled"):
        client.send(draft, permit=permit(draft), now=NOW)


def test_contract_uses_paper_host_and_exact_headers_under_fake_opener(tmp_path, monkeypatch):
    _, draft, *_ = setup(tmp_path)
    seen = []
    class FakeOpener:
        def open(self, req, timeout):
            seen.append((req, timeout))
            return FakeResponse(json.dumps({
                "id": "fixture-only", "client_order_id": draft.client_order_id,
            }).encode())
    monkeypatch.setattr(api, "NETWORK_PAPER_WRITES_ENABLED", True)
    monkeypatch.setattr(api, "build_opener", lambda *_: FakeOpener())
    client = api.AlpacaPaperPostTransport(api.RestrictedPaperAuth("FAKE_KEY", "FAKE_SECRET"))
    status, result = client.send(draft, permit=permit(draft), now=NOW)
    assert status == 200
    assert result["client_order_id"] == draft.client_order_id
    assert len(seen) == 1
    req, timeout = seen[0]
    u = urlsplit(req.full_url)
    assert f"{u.scheme}://{u.netloc}" == "https://paper-api.alpaca.markets"
    assert u.path == "/v2/orders"
    assert req.get_method() == "POST"
    assert timeout == 10
    assert req.headers["Apca-api-key-id"] == "FAKE_KEY"
    assert req.headers["Apca-api-secret-key"] == "FAKE_SECRET"
    assert json.loads(req.data)["client_order_id"] == draft.client_order_id
    assert json.loads(req.data)["extended_hours"] is False
    assert "FAKE_SECRET" not in repr(client._auth)


@pytest.mark.parametrize("updates", [
    {"owner_confirmed": False},
    {"verified_account_slot": False},
    {"key_slot": "ALPACA_API_KEY2"},
    {"client_order_id": "other"},
    {"expires_at": NOW - timedelta(seconds=1)},
])
def test_wrong_permission_cannot_make_http_request(tmp_path, monkeypatch, updates):
    _, draft, *_ = setup(tmp_path)
    monkeypatch.setattr(api, "NETWORK_PAPER_WRITES_ENABLED", True)
    monkeypatch.setattr(api, "build_opener", lambda *_: pytest.fail("unexpected HTTP"))
    with pytest.raises(PaperDeskError):
        api.AlpacaPaperPostTransport(
            api.RestrictedPaperAuth("FAKE_KEY", "FAKE_SECRET")
        ).send(draft, permit=replace(permit(draft), **updates), now=NOW)


def test_broker_http_403_is_redacted_and_never_retried(tmp_path, monkeypatch):
    _, draft, *_ = setup(tmp_path)
    calls = []
    class Denied:
        def open(self, req, timeout):
            calls.append("one")
            raise HTTPError(req.full_url, 403, "forbidden", {}, io.BytesIO(b"PRIVATE_ERROR_BODY"))
    monkeypatch.setattr(api, "NETWORK_PAPER_WRITES_ENABLED", True)
    monkeypatch.setattr(api, "build_opener", lambda *_: Denied())
    result = api.AlpacaPaperPostTransport(
        api.RestrictedPaperAuth("FAKE_KEY", "FAKE_SECRET")
    ).send(draft, permit=permit(draft), now=NOW)
    assert result == (403, {})
    assert len(calls) == 1


def test_timeout_raises_uncertain_does_not_retry(tmp_path, monkeypatch):
    _, draft, *_ = setup(tmp_path)
    seen = []
    class Timeout:
        def open(self, req, timeout):
            seen.append(True)
            raise URLError("timeout")
    monkeypatch.setattr(api, "NETWORK_PAPER_WRITES_ENABLED", True)
    monkeypatch.setattr(api, "build_opener", lambda *_: Timeout())
    with pytest.raises(PaperDeskError, match="do not retry"):
        api.AlpacaPaperPostTransport(
            api.RestrictedPaperAuth("FAKE_KEY", "FAKE_SECRET")
        ).send(draft, permit=permit(draft), now=NOW)
    assert len(seen) == 1
