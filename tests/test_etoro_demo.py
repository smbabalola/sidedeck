"""eToro DEMO read-only adapter: synthetic fixtures only, no network, no credentials.

All IDs and amounts below are invented. Nothing here contacts eToro.
"""
import ast
import inspect
import io
import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from urllib.error import HTTPError

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect as sa_inspect

from sidedeck.application import etoro_demo_portfolio as cli
from sidedeck.domain.etoro_demo import EtoroDemoDataError, parse_demo_portfolio
from sidedeck.domain.etoro_demo_books import (
    AI_TRADING_BOOK, DEMO_BOOKS, TRADINGAGENTS_BOOK, UNATTRIBUTED_BOOK, EtoroDemoBookError,
    OrderAttribution, baseline_from, reconcile_demo, require_sidedeck_owned,
)
from sidedeck.infrastructure import etoro_demo_client
from sidedeck.infrastructure.etoro_demo_client import (
    DEMO_PORTFOLIO_PATH, EtoroDemoAccessError, EtoroDemoReadClient,
)
from sidedeck.infrastructure.etoro_demo_store import EtoroDemoStore

NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
USD = 1   # synthetic: the real USD accountCurrencyId still needs owner confirmation


def position(position_id, instrument_id=1001, *, order_id=None, units="2", amount="300",
             is_buy=True, pnl="12.5", **changes):
    row = {"positionID": position_id, "instrumentID": instrument_id,
           "orderID": order_id if order_id is not None else 9000 + position_id,
           "isBuy": is_buy, "units": units, "amount": amount, "leverage": 1,
           "openDateTime": "2026-09-01T14:30:00Z", "unrealizedPnL": {"pnL": pnl}}
    row.update(changes)
    return row


BASELINE_ROWS = [position(11), position(12, 1001, units="1"), position(13, 1002),
                 position(14, 1003, is_buy=False)]


def payload(positions=None, **changes):
    portfolio = {"credit": "5000.25", "bonusCredit": "100", "accountCurrencyId": USD,
                 "unrealizedPnL": "40", "positions": list(BASELINE_ROWS if positions is None
                                                          else positions),
                 "mirrors": [], "orders": [], "ordersForOpen": [], "ordersForClose": [],
                 "ordersForCloseMultiple": [], "entryOrders": [], "exitOrders": [],
                 "stockOrders": []}
    portfolio.update(changes)
    return {"clientPortfolio": portfolio}


def snap(data=None, at=NOW):
    return parse_demo_portfolio(payload() if data is None else data, observed_at=at)


# --- parsing and figures -----------------------------------------------------

def test_parses_positions_with_decimal_and_keeps_identity_by_position_id():
    snapshot = snap()
    assert [p.position_id for p in snapshot.positions] == [11, 12, 13, 14]
    assert all(isinstance(p.units, Decimal) for p in snapshot.positions)
    assert snapshot.credit == Decimal("5000.25") and snapshot.bonus_credit == Decimal("100")
    assert snapshot.unrealized_pnl().value == Decimal("50.0")


def test_available_cash_follows_documented_formula_and_ignores_bonus():
    data = payload(ordersForOpen=[{"orderID": 1, "amount": "200", "mirrorID": 0},
                                  {"orderID": 2, "amount": "999", "mirrorID": 7}],
                   orders=[{"orderID": 3, "amount": "50.25"}])
    cash = snap(data).available_cash_usd(usd_currency_id=USD)
    assert (cash.status, cash.value) == ("AVAILABLE", Decimal("4750.00"))
    assert snap(payload(credit="0")).available_cash_usd(usd_currency_id=USD).value == 0


@pytest.mark.parametrize("data, currency, reason", [
    (payload(credit=None), USD, "credit not reported"),
    (payload(), None, "not confirmed as USD"),
    (payload(accountCurrencyId=2), USD, "not confirmed as USD"),
    (payload(ordersForOpen=[{"orderID": 1, "amount": "5"}]), USD, "mirrorID"),
    (payload(orders=[{"orderID": 1}]), USD, "lacks amount"),
])
def test_cash_is_unavailable_never_guessed(data, currency, reason):
    cash = snap(data).available_cash_usd(usd_currency_id=currency)
    assert cash.value is None and cash.status == "UNAVAILABLE" and reason in cash.reason


def test_pnl_unavailable_with_mirrors_or_missing_position_pnl():
    assert snap(payload(mirrors=[{"mirrorID": 5}])).unrealized_pnl().status == "UNAVAILABLE"
    missing = payload([position(11, unrealizedPnL=None)])
    assert snap(missing).unrealized_pnl().status == "UNAVAILABLE"


@pytest.mark.parametrize("data, message", [
    ({"x": 1}, "clientPortfolio missing"),
    (payload(stockOrders=None), "stockOrders"),
    (payload([position(11), position(11)]), "duplicate positionID"),
    (payload([position(11, units="-1")]), "positive"),
    (payload([position(11, units="0")]), "positive"),
    (payload([position(11, units="NaN")]), "finite"),
    (payload([position(11, units=True)]), "numeric"),
    (payload([position(11, positionID="11")]), "positionID"),
    (payload([position(11, isBuy="yes")]), "direction"),
    (payload([position(11, openDateTime="2026-09-01T14:30:00")]), "timezone"),
    (payload(credit="abc"), "numeric"),
])
def test_malformed_demo_data_fails_closed(data, message):
    with pytest.raises(EtoroDemoDataError, match=message):
        snap(data)


def test_stale_or_future_snapshots_are_refused():
    snapshot = snap()
    with pytest.raises(EtoroDemoDataError, match="stale"):
        snapshot.require_fresh(NOW + timedelta(minutes=6))
    with pytest.raises(EtoroDemoDataError, match="future"):
        snapshot.require_fresh(NOW - timedelta(minutes=1))


# --- baseline, books and reconciliation ----------------------------------------

def test_existing_positions_are_an_unattributed_read_only_baseline():
    snapshot = snap()
    baseline = baseline_from(snapshot)
    report = reconcile_demo(snapshot, baseline=baseline, attributions=(), now=NOW,
                            usd_currency_id=USD)
    assert report.status == "MATCHED" and report.execution_enabled is False
    assert report.books[UNATTRIBUTED_BOOK].position_ids == (11, 12, 13, 14)
    assert report.books[TRADINGAGENTS_BOOK].position_ids == ()
    assert report.books[AI_TRADING_BOOK].position_ids == ()
    assert report.books[UNATTRIBUTED_BOOK].units_by_instrument == {
        1001: Decimal("3"), 1002: Decimal("2"), 1003: Decimal("-2")}   # multi-lot, short sign
    assert all(view.allocation_status.startswith("NOT_ALLOCATED") for view in report.books.values())
    for position_id in (11, 12, 13, 14):
        with pytest.raises(EtoroDemoBookError, match="read-only"):
            require_sidedeck_owned(position_id, baseline=baseline, attributions=(), snapshot=snapshot)


def test_new_positions_are_attributed_by_order_id_never_by_instrument():
    baseline = baseline_from(snap())
    rows = BASELINE_ROWS + [position(21, 1001, order_id=501), position(22, 1001, order_id=502),
                            position(23, 1001, order_id=503)]
    snapshot = snap(payload(rows))
    attributions = (OrderAttribution(501, TRADINGAGENTS_BOOK), OrderAttribution(502, AI_TRADING_BOOK))
    report = reconcile_demo(snapshot, baseline=baseline, attributions=attributions, now=NOW)
    assert report.books[TRADINGAGENTS_BOOK].position_ids == (21,)
    assert report.books[AI_TRADING_BOOK].position_ids == (22,)
    # Same instrument as baseline and strategy positions, but no SideDeck order: unexplained.
    assert 23 in report.books[UNATTRIBUTED_BOOK].position_ids
    assert report.status == "DISCREPANCY"
    assert report.discrepancies == ("position 23 has no SideDeck attribution",)
    assert report.books[TRADINGAGENTS_BOOK].unrealized_pnl.value == Decimal("12.5")
    assert require_sidedeck_owned(21, baseline=baseline, attributions=attributions,
                                  snapshot=snapshot) == TRADINGAGENTS_BOOK
    with pytest.raises(EtoroDemoBookError, match="no SideDeck order attribution"):
        require_sidedeck_owned(23, baseline=baseline, attributions=attributions, snapshot=snapshot)


@pytest.mark.parametrize("rows, extra, expected", [
    (BASELINE_ROWS[:3], {}, "baseline position 14 is no longer open"),
    (BASELINE_ROWS[:3] + [position(14, 1003, is_buy=False, units="1")], {},
     "baseline position 14 changed outside SideDeck"),
    (BASELINE_ROWS, {"orders": [{"orderID": 77, "amount": "10"}]},
     "pending orders order is not a SideDeck order"),
    (BASELINE_ROWS, {"mirrors": [{"mirrorID": 3}]}, "copy/mirror positions are present and are not supported"),
])
def test_baseline_changes_unknown_orders_and_mirrors_are_discrepancies(rows, extra, expected):
    baseline = baseline_from(snap())
    report = reconcile_demo(snap(payload(rows, **extra)), baseline=baseline, attributions=(),
                            now=NOW)
    assert report.status == "DISCREPANCY" and expected in report.discrepancies


def test_reports_are_per_book_and_never_combined():
    report = reconcile_demo(snap(), baseline=baseline_from(snap()), attributions=(), now=NOW)
    assert set(report.books) == set(DEMO_BOOKS)
    summary = cli.safe_summary(report, request_id="r", baseline_count=4)
    text = json.dumps(summary)
    assert "total" not in text and "combined" not in text
    for secret_ish in ("5000.25", "12.5", "1001", "9011"):          # values and IDs never printed
        assert secret_ish not in text


def test_attributions_cannot_name_the_unattributed_book_or_a_baseline_order():
    baseline = baseline_from(snap())
    with pytest.raises(EtoroDemoBookError, match="strategy book"):
        reconcile_demo(snap(), baseline=baseline,
                       attributions=(OrderAttribution(1, UNATTRIBUTED_BOOK),), now=NOW)
    report = reconcile_demo(snap(), baseline=baseline,
                            attributions=(OrderAttribution(9011, TRADINGAGENTS_BOOK),), now=NOW)
    assert "attributed order 9011 belongs to a baseline position" in report.discrepancies
    assert 11 in report.books[UNATTRIBUTED_BOOK].position_ids        # baseline wins


# --- durable store ---------------------------------------------------------------

def test_store_captures_baseline_once_and_protects_it(tmp_path):
    store = EtoroDemoStore(str(tmp_path / "demo.sqlite"))
    with pytest.raises(EtoroDemoBookError, match="capture the Demo baseline"):
        store.record_order_attribution(order_id=501, strategy="tradingagents", at=NOW)
    assert store.capture_baseline(snap())
    assert not store.capture_baseline(snap())                         # idempotent
    with pytest.raises(EtoroDemoBookError, match="different Demo baseline"):
        store.capture_baseline(snap(payload(BASELINE_ROWS[:2])))
    assert [b.position_id for b in store.baseline()] == [11, 12, 13, 14]
    with pytest.raises(EtoroDemoBookError, match="baseline position"):
        store.record_order_attribution(order_id=9011, strategy="tradingagents", at=NOW)
    with pytest.raises(EtoroDemoBookError, match="not a SideDeck strategy"):
        store.record_order_attribution(order_id=501, strategy="unattributed", at=NOW)
    store.record_order_attribution(order_id=501, strategy="tradingagents", at=NOW)
    store.record_order_attribution(order_id=501, strategy="tradingagents", at=NOW)   # idempotent
    with pytest.raises(EtoroDemoBookError, match="another strategy"):
        store.record_order_attribution(order_id=501, strategy="ai-trading", at=NOW)
    assert store.attributions() == (OrderAttribution(501, TRADINGAGENTS_BOOK),)


def test_empty_account_is_still_a_captured_baseline(tmp_path):
    store = EtoroDemoStore(str(tmp_path / "empty.sqlite"))
    assert store.capture_baseline(snap(payload([])))
    assert store.baseline_captured() and store.baseline() == ()


def test_concurrent_baseline_capture_records_exactly_one(tmp_path):
    path = str(tmp_path / "race.sqlite")
    EtoroDemoStore(path)
    results: list[bool] = []
    barrier = threading.Barrier(6)

    def capture():
        barrier.wait()
        results.append(EtoroDemoStore(path).capture_baseline(snap()))

    threads = [threading.Thread(target=capture) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results.count(True) == 1
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM etoro_demo_baseline").fetchone() == (4,)


# --- client: allowlist, GET only, no redirect, sanitised errors -------------------

class FakeResponse:
    def __init__(self, body, status=200):
        self.status, self._body = status, json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit):
        return self._body[:limit]


class FakeOpener:
    def __init__(self, result):
        self.result, self.requests = result, []

    def open(self, request, timeout):
        self.requests.append(request)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def client_with(monkeypatch, result):
    opener = FakeOpener(result)
    monkeypatch.setattr(etoro_demo_client, "build_opener", lambda *handlers: opener)
    return EtoroDemoReadClient(api_key="synthetic-api-key", user_key="synthetic-user-key"), opener


def test_client_sends_one_honest_get_to_the_demo_path_only(monkeypatch):
    client, opener = client_with(monkeypatch, FakeResponse(payload()))
    data, request_id = client.read_demo_portfolio()
    assert data == payload() and len(opener.requests) == 1
    request = opener.requests[0]
    assert request.get_method() == "GET"
    assert request.full_url == "https://public-api.etoro.com" + DEMO_PORTFOLIO_PATH
    assert request.get_header("User-agent") == "SideDeck/0.1 (read-only demo portfolio)"
    assert request.get_header("X-request-id") == request_id
    for path in ("/api/v1/trading/info/real/pnl",
                 "/api/v1/trading/execution/demo/market-open-orders/by-amount",
                 DEMO_PORTFOLIO_PATH + "?x=1"):
        with pytest.raises(PermissionError):
            client._get(path)
    assert len(opener.requests) == 1
    assert "synthetic" not in repr(client)


def _http_error(code, body):
    headers = {"CF-Ray": "synthetic-ray-LHR"}
    return HTTPError("https://public-api.etoro.com", code, "x", headers,  # type: ignore[arg-type]
                     io.BytesIO(body))


@pytest.mark.parametrize("error, classification", [
    (_http_error(401, b"{}"), "AUTH_REJECTED"),
    (_http_error(403, b'{"title": "Error 1010: Access denied"}'), "CLOUDFLARE_1010"),
    (_http_error(403, b'{"message": "forbidden"}'), "ACCESS_DENIED"),
    (_http_error(429, b"{}"), "RATE_LIMITED"),
    (_http_error(500, b"{}"), "UNEXPECTED_RESPONSE"),
])
def test_client_failures_are_sanitised_and_not_retried(monkeypatch, error, classification):
    client, opener = client_with(monkeypatch, error)
    with pytest.raises(EtoroDemoAccessError) as caught:
        client.read_demo_portfolio()
    assert caught.value.classification == classification and len(opener.requests) == 1
    assert caught.value.cf_ray == "synthetic-ray-LHR"
    assert "synthetic-api-key" not in str(caught.value)
    assert "synthetic-user-key" not in str(caught.value)


def test_client_module_has_no_write_capability():
    source = inspect.getsource(etoro_demo_client)
    code = source.split('"""', 2)[2]                                   # skip the module docstring
    for forbidden in ('"POST"', '"PUT"', '"DELETE"', "/real/", "execution"):
        assert forbidden not in code, forbidden
    names = {node.name for node in ast.walk(ast.parse(source)) if isinstance(node, ast.FunctionDef)}
    assert not names & {"submit", "place_order", "close_position", "cancel_order", "post"}


def test_cli_sends_nothing_without_confirmation_or_keys(monkeypatch, tmp_path, capsys):
    def boom(*args):
        raise AssertionError("network must not be touched")

    monkeypatch.setattr(etoro_demo_client, "build_opener", boom)
    with pytest.raises(SystemExit):
        cli.main(["--db", str(tmp_path / "x.sqlite")])
    monkeypatch.delenv("ETORO_API_KEY", raising=False)
    monkeypatch.delenv("ETORO_USER_KEY", raising=False)
    with pytest.raises(SystemExit):
        cli.main(["--confirm-owner-demo-read", "--db", str(tmp_path / "x.sqlite")])
    assert "nothing sent" in capsys.readouterr().err


def test_cli_end_to_end_with_synthetic_response_prints_only_counts(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("ETORO_API_KEY", "synthetic-api-key")
    monkeypatch.setenv("ETORO_USER_KEY", "synthetic-user-key")
    client_with(monkeypatch, FakeResponse(payload()))
    code = cli.main(["--confirm-owner-demo-read", "--db", str(tmp_path / "demo.sqlite"),
                     "--capture-baseline"])
    output = capsys.readouterr().out
    summary = json.loads(output)
    assert code == 0 and summary["status"] == "MATCHED" and summary["baseline_positions"] == 4
    assert summary["available_cash_usd_status"] == "UNAVAILABLE"      # USD id not confirmed
    assert summary["orders_submitted"] == 0 and summary["execution_enabled"] is False
    for leaked in ("5000.25", "synthetic-api-key", "9011", "1001"):
        assert leaked not in output


# --- migration ---------------------------------------------------------------------

def test_0005_round_trip_and_downgrade_protection(tmp_path: Path):
    path = tmp_path / "m.db"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{path}")
    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{path}")
    try:
        assert {"etoro_demo_baseline", "etoro_demo_order_attribution",
                "etoro_demo_baseline_capture"} <= set(sa_inspect(engine).get_table_names())
    finally:
        engine.dispose()
    command.downgrade(config, "0004_proposal_audit")
    command.upgrade(config, "head")
    EtoroDemoStore(str(path)).capture_baseline(snap())
    with pytest.raises(Exception, match="refusing to drop history"):
        command.downgrade(config, "0004_proposal_audit")
