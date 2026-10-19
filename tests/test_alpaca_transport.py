import pytest

from sidedeck.infrastructure.alpaca_paper import AlpacaPaperBinding
from sidedeck.infrastructure.alpaca_transport import PaperReadError, make_paper_get


def test_disallowed_endpoints_never_require_credentials():
    get = make_paper_get(AlpacaPaperBinding())
    for path in ("/v2/orders", "/v2/account/activities", "https://api.alpaca.markets/v2/account"):
        with pytest.raises(PermissionError):
            get(path)


def test_missing_credentials_fail_closed(monkeypatch):
    monkeypatch.delenv("ALPACA_API_KEY2", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET_KEY2", raising=False)
    with pytest.raises(PaperReadError, match="credentials unavailable"):
        make_paper_get(AlpacaPaperBinding())("/v2/account")


def test_invalid_timeout():
    with pytest.raises(ValueError):
        make_paper_get(AlpacaPaperBinding(), timeout_seconds=0)
