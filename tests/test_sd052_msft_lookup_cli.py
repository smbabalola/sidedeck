"""SD-052 launcher: offline only (fake opener via monkeypatched build_opener)."""
import json
from datetime import datetime, timezone
from urllib.request import ProxyHandler

import pytest

from sidedeck.application import sd050_msft_instrument_lookup as lookup
from sidedeck.application import sd052_msft_lookup_cli as cli
from sidedeck.infrastructure import etoro_demo_write_transport as order_transport
from sidedeck.infrastructure.etoro_demo_store import EtoroDemoStore

ENV = {"ETORO_DEMO_TRADE_API_KEY": "app-key-111", "ETORO_DEMO_TRADE_USER_KEY": "user-key-222"}
ITEM = {"instrumentId": 7001, "internalSymbolFull": "MSFT", "internalExchangeName": "Nasdaq",
        "instrumentType": "Stocks", "displayname": "Microsoft", "isDelisted": False,
        "isHiddenFromClient": False}


class Response:
    status = 200

    def read(self, n):
        return json.dumps({"items": [ITEM]}).encode()[:n]


class FakeOpener:
    def __init__(self, error=None):
        self.requests, self.error, self.handlers = [], error, ()

    def open(self, request, timeout):
        self.requests.append(request)
        assert lookup.LOOKUP_NETWORK_ENABLED is True
        assert order_transport.NETWORK_TRANSPORT_ENABLED is False
        if self.error:
            raise self.error
        return Response()


@pytest.fixture
def rig(tmp_path, monkeypatch):
    rows = [{"positionID": n, "instrumentID": 1000 + n, "orderID": 9000 + n, "isBuy": True,
             "units": 1, "amount": 100, "leverage": 1, "openDateTime": "2026-09-01T14:30:00Z",
             "unrealizedPnL": {"pnL": 0}} for n in (1, 2, 3, 4)]
    payload = {"clientPortfolio": {"positions": rows, "credit": 1, "bonusCredit": 0,
                                   "accountCurrencyId": 1, "mirrors": [], "orders": [],
                                   "ordersForOpen": [], "ordersForClose": [],
                                   "ordersForCloseMultiple": [], "entryOrders": [],
                                   "exitOrders": [], "stockOrders": []}}
    db = tmp_path / "etoro_demo.sqlite3"
    EtoroDemoStore(str(db)).capture_baseline(payload, observed_at=datetime.now(timezone.utc),
                                             expected_positions=4)
    monkeypatch.setattr(lookup, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cli, "BASELINE_DB", str(db))
    monkeypatch.setattr(cli, "EVIDENCE_PATH", str(tmp_path / "sd052-msft-instrument.json"))
    lookup._reserve(lookup.budget_path_for("SD-050"))          # SD-050 exhausted state
    opener = FakeOpener()

    def build(*handlers):
        opener.handlers = handlers
        return opener
    monkeypatch.setattr(lookup, "build_opener", build)
    return opener


def test_sends_exactly_one_read_only_request_then_relocks(rig):
    result = cli.run(ENV)
    assert result["status"] == "RESOLVED_PARTIALLY_VERIFIED" and result["instrument_id"] == 7001
    assert len(rig.requests) == 1 and rig.requests[0].get_method() == "GET"
    assert rig.requests[0].full_url.startswith(lookup.SEARCH_URL + "?internalSymbolFull=MSFT&")
    assert any(isinstance(h, ProxyHandler) for h in rig.handlers)
    assert any(isinstance(h, lookup._NoRedirect) for h in rig.handlers)
    assert lookup.LOOKUP_NETWORK_ENABLED is False
    assert order_transport.NETWORK_TRANSPORT_ENABLED is False
    assert lookup.attempts_consumed(lookup.budget_path_for("SD-052")) == 1
    with pytest.raises(cli.LauncherRefused, match="already consumed"):
        cli.run(ENV)
    assert len(rig.requests) == 1


def test_relocks_on_unexpected_error_and_attempt_stays_consumed(rig):
    rig.error = RuntimeError("boom")
    with pytest.raises(RuntimeError):
        cli.run(ENV)
    assert lookup.LOOKUP_NETWORK_ENABLED is False
    assert lookup.attempts_consumed(lookup.budget_path_for("SD-052")) == 1


@pytest.mark.parametrize("setup,match", [
    (lambda mp: mp.setattr(lookup, "LOOKUP_NETWORK_ENABLED", True), "lookup network"),
    (lambda mp: mp.setattr(lookup, "AUTHORIZED_LOOKUP_IDS", frozenset()), "not an open"),
    (lambda mp: mp.setattr(lookup, "EXHAUSTED_LOOKUP_IDS", frozenset({"SD-050", "SD-052"})),
     "exhausted"),
])
def test_preconditions_refuse_without_sending(rig, monkeypatch, setup, match):
    setup(monkeypatch)
    with pytest.raises(cli.LauncherRefused, match=match):
        cli.run(ENV)
    assert rig.requests == []
    assert lookup.attempts_consumed(lookup.budget_path_for("SD-052")) == 0


def test_refuses_if_sd050_not_exhausted(rig, tmp_path):
    (tmp_path / "sd050-auth-budget.sqlite3").unlink()
    with pytest.raises(cli.LauncherRefused, match="SD-050"):
        cli.run(ENV)
    assert rig.requests == []


def test_preflight_failure_does_not_consume_attempt(rig):
    with pytest.raises(PermissionError):
        cli.run({**ENV, "ETORO_API_KEY": "legacy"})
    assert rig.requests == [] and lookup.LOOKUP_NETWORK_ENABLED is False
    assert lookup.attempts_consumed(lookup.budget_path_for("SD-052")) == 0


@pytest.mark.parametrize("argv", [[], ["--confirm-sd052", "--authorization-id", "SD-053"],
                                  ["--confirm-sd052", "--retries", "1"]])
def test_cli_has_no_bypass_options(rig, argv):
    with pytest.raises(SystemExit):
        cli.main(argv)
    assert rig.requests == []


def test_source_locks_and_authorization_state():
    assert lookup.LOOKUP_NETWORK_ENABLED is False
    assert order_transport.NETWORK_TRANSPORT_ENABLED is False
    assert "SD-050" in lookup.EXHAUSTED_LOOKUP_IDS


def test_launcher_never_references_order_transport():
    source = open(cli.__file__, encoding="utf-8").read()
    assert "NETWORK_TRANSPORT_ENABLED =" not in source
    assert "etoro_demo_write_transport" not in source
