"""Alpaca PAPER-only SideDeck portfolio inspection: offline contract tests."""

from datetime import datetime, timezone
from email.message import Message
import json
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

import pytest

from sidedeck import paper
from sidedeck.domain.alpaca_paper import (
    AlpacaPaperAccessBlocked, AlpacaPaperError, AlpacaPaperReadClient,
    PAPER_HOST, validate_paper_get,
)

NOW = datetime(2026, 10, 18, 19, tzinfo=timezone.utc)


class Transport:
    def __init__(self, account=None, positions=None, orders=None, status=200):
        self.status = status
        self.values = {
            "/v2/account": account if account is not None else {
                "status": "ACTIVE", "cash": "1000", "equity": "1000",
                "buying_power": "1000", "multiplier": "1",
            },
            "/v2/positions": positions if positions is not None else [],
            "/v2/orders": orders if orders is not None else [],
        }
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get(self, path, params):
        self.calls.append((path, dict(params)))
        return self.status, json.dumps(self.values[path]).encode()


def position(symbol="AAPL"):
    return {
        "symbol": symbol, "asset_class": "us_equity", "side": "long",
        "qty": "0.5", "avg_entry_price": "110", "market_value": "75",
    }


def order():
    return {
        "client_order_id": "sidedeck-fixture-intent", "symbol": "AAPL",
        "side": "buy", "qty": "0.5", "filled_qty": "0",
        "status": "new",
    }


def test_reads_only_paper_account_positions_open_orders() -> None:
    transport = Transport(positions=[position()], orders=[order()])
    view = AlpacaPaperReadClient(transport).inspect(observed_at=NOW)
    assert view.source == "ALPACA_PAPER"
    assert view.account.cash == 1000
    assert view.positions[0].symbol == "AAPL"
    assert view.positions[0].quantity == 0.5
    assert view.open_orders[0].client_order_id == "sidedeck-fixture-intent"
    assert view.broker_scope == "SINGLE_BROKER_ACCOUNT_NOT_TWO_STRATEGY_LEDGERS"
    assert transport.calls == [
        ("/v2/account", {}),
        ("/v2/positions", {}),
        ("/v2/orders", {"status": "open", "limit": "100"}),
    ]


def test_dry_run_never_reads_environment_or_uses_network(monkeypatch, capsys) -> None:
    monkeypatch.setattr("sys.argv", ["paper", "--dry-run"])
    monkeypatch.setattr(paper.PaperCredentials, "from_environment", lambda: pytest.fail("secret read"))
    assert paper.main() == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["mode"] == "FIXTURE_NOT_REAL"
    assert printed["order_submission_enabled"] is False
    assert printed["two_broker_accounts_verified"] is False
    assert printed["account"]["cash"] == "1000"


def test_no_network_without_explicit_opt_in_even_if_credentials_exist(monkeypatch) -> None:
    monkeypatch.setenv("ALPACA_API_KEY", "DUMMY_KEY")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "DUMMY_SECRET")
    monkeypatch.setattr("sys.argv", ["paper"])
    with pytest.raises(SystemExit):
        paper.main()


def test_secret_variable_aliases_are_non_printing(monkeypatch) -> None:
    monkeypatch.setenv("ALPACA_API_KEY", "DUMMY_KEY")
    for k in ("ALPACA_SECRET_KEY", "ALPACA_API_SECRET_KEY", "APCA_API_SECRET_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "DUMMY_SECRET")
    auth = paper.PaperCredentials.from_environment()
    assert auth.api_key == "DUMMY_KEY"
    assert "DUMMY_SECRET" not in repr(auth)
    monkeypatch.setenv("APCA_API_SECRET_KEY", "OTHER_SECRET")
    with pytest.raises(ValueError, match="conflicting"):
        paper.PaperCredentials.from_environment()


@pytest.mark.parametrize("path,params", [
    ("/v2/orders", {"status": "all", "limit": "100"}),
    ("/v2/account/configurations", {}),
    ("/v2/positions/AAPL", {}),
    ("/v2/orders", {"status": "open", "limit": "1000"}),
    ("/v2/orders", {}),
    ("/v2/orders", {"status": "open", "limit": "100", "side": "buy"}),
    ("/v2/account/../orders", {}),
    ("/v2/orders/123", {}),
    ("/v2/crypto", {}),
    ("//external.example/v2/account", {}),
])
def test_get_allowlist_blocks_nonpaper_or_mutating_paths(path, params) -> None:
    with pytest.raises(AlpacaPaperError):
        validate_paper_get(path, params)


@pytest.mark.parametrize("bad_positions", [
    [position("BTCUSD")],
    [{**position(), "side": "short"}],
    [position(), position()],
    [{**position(), "qty": "NaN"}],
])
def test_unapproved_short_duplicate_or_invalid_position_fail_closed(bad_positions) -> None:
    with pytest.raises(AlpacaPaperError):
        AlpacaPaperReadClient(Transport(positions=bad_positions)).inspect(observed_at=NOW)


@pytest.mark.parametrize("bad_orders", [
    [{**order(), "symbol": "TSLA"}],
    [{**order(), "side": "short"}],
    [{**order(), "filled_qty": "1"}],
    [{**order(), "status": "filled"}],
])
def test_unexpected_open_orders_fail_closed(bad_orders) -> None:
    with pytest.raises(AlpacaPaperError):
        AlpacaPaperReadClient(Transport(orders=bad_orders)).inspect(observed_at=NOW)


@pytest.mark.parametrize("status", [401, 403])
def test_access_errors_redacted_without_retry(status) -> None:
    transport = Transport(status=status)
    with pytest.raises(AlpacaPaperAccessBlocked, match=str(status)):
        AlpacaPaperReadClient(transport).inspect(observed_at=NOW)
    assert len(transport.calls) == 1


def test_headers_and_hostname_use_alpaca_paper_only(monkeypatch) -> None:
    reqs = []

    class Response:
        status = 200
        def read(self, n):
            return b'{"status":"ACTIVE"}'
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return None

    class Opener:
        def open(self, request, timeout):
            reqs.append(request)
            assert timeout == 10
            return Response()

    monkeypatch.setattr(paper, "build_opener", lambda *_: Opener())
    auth = paper.PaperCredentials("DUMMY_KEY", "DUMMY_SECRET")
    status, _ = paper.AlpacaPaperHttpTransport(auth).get("/v2/account", {})
    assert status == 200
    assert len(reqs) == 1
    req = reqs[0]
    u = urlsplit(req.full_url)
    assert f"{u.scheme}://{u.netloc}" == PAPER_HOST
    assert req.get_method() == "GET"
    assert dict(parse_qs(u.query)) == {}
    assert req.headers["Apca-api-key-id"] == "DUMMY_KEY"
    assert req.headers["Apca-api-secret-key"] == "DUMMY_SECRET"


def test_http_error_never_returns_provider_error_body(monkeypatch) -> None:
    class Opener:
        def open(self, req, timeout):
            raise HTTPError(req.full_url, 403, "denied", Message(), __import__("io").BytesIO(b"PRIVATE-BODY"))

    monkeypatch.setattr(paper, "build_opener", lambda *_: Opener())
    transport = paper.AlpacaPaperHttpTransport(paper.PaperCredentials("fake", "secret"))
    status, body = transport.get("/v2/account", {})
    assert status == 403
    assert body == b""


def test_single_paper_account_cannot_be_two_broker_ledgers() -> None:
    view = AlpacaPaperReadClient(Transport()).inspect(observed_at=NOW)
    assert view.broker_scope != "TWO_INDEPENDENT_STRATEGY_ACCOUNTS"
