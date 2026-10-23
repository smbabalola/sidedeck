import pytest

from sidedeck.infrastructure.alpaca_paper import AlpacaPaperBinding
from sidedeck.infrastructure.alpaca_transport import PaperReadError, make_paper_get


def test_disallowed_endpoints_never_require_credentials():
    get = make_paper_get(AlpacaPaperBinding())
    for path in ("/v2/orders", "/v2/orders?status=all", "/v2/account/activities", "https://api.alpaca.markets/v2/account"):
        with pytest.raises(PermissionError):
            get(path)


def test_missing_credentials_fail_closed(monkeypatch):
    monkeypatch.delenv("ALPACA_API_KEY2", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET_KEY2", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET2", raising=False)
    with pytest.raises(PaperReadError, match="credentials unavailable"):
        make_paper_get(AlpacaPaperBinding())("/v2/account")


def test_invalid_timeout():
    with pytest.raises(ValueError):
        make_paper_get(AlpacaPaperBinding(), timeout_seconds=0)


class _FakeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def read(self, _limit):
        return b'{"ok": true}'


def _capture_requests(monkeypatch):
    sent = []

    class _Opener:
        def open(self, request, timeout):
            sent.append(request)
            return _FakeResponse()

    monkeypatch.setattr(
        "sidedeck.infrastructure.alpaca_transport.build_opener", lambda *_a: _Opener()
    )
    return sent


def _clear_paper_env(monkeypatch):
    for name in ("ALPACA_API_KEY", "ALPACA_API_SECRET", "ALPACA_API_KEY2",
                 "ALPACA_API_SECRET_KEY2", "ALPACA_API_SECRET2"):
        monkeypatch.delenv(name, raising=False)


def test_slot_b_secret_alias_alpaca_api_secret2_is_accepted(monkeypatch):
    _clear_paper_env(monkeypatch)
    sent = _capture_requests(monkeypatch)
    monkeypatch.setenv("ALPACA_API_KEY2", "KEY_B")
    monkeypatch.setenv("ALPACA_API_SECRET2", "SECRET_B")
    assert make_paper_get(AlpacaPaperBinding())("/v2/account") == {"ok": True}
    assert len(sent) == 1
    assert sent[0].get_header("Apca-api-secret-key") == "SECRET_B"
    assert sent[0].get_method() == "GET"


def test_conflicting_slot_b_secret_aliases_fail_before_any_request(monkeypatch):
    _clear_paper_env(monkeypatch)
    sent = _capture_requests(monkeypatch)
    monkeypatch.setenv("ALPACA_API_KEY2", "KEY_B")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY2", "SECRET_B")
    monkeypatch.setenv("ALPACA_API_SECRET2", "DIFFERENT")
    with pytest.raises(PaperReadError, match="conflicting") as info:
        make_paper_get(AlpacaPaperBinding())("/v2/account")
    assert "SECRET_B" not in str(info.value) and "DIFFERENT" not in str(info.value)
    assert sent == []


def test_slot_a_signaldeck_secret_is_never_used(monkeypatch):
    _clear_paper_env(monkeypatch)
    sent = _capture_requests(monkeypatch)
    monkeypatch.setenv("ALPACA_API_KEY2", "KEY_B")
    monkeypatch.setenv("ALPACA_API_SECRET", "SECRET_A")
    with pytest.raises(PaperReadError, match="credentials unavailable"):
        make_paper_get(AlpacaPaperBinding())("/v2/account")
    assert sent == []
