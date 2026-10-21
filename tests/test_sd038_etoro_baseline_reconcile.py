"""SD-038 one-shot baseline reconciliation: offline only, fake client, synthetic IDs."""
import json
import os
from datetime import datetime, timezone

import pytest

from sidedeck.application import sd038_etoro_baseline_reconcile as sd038
from sidedeck.application.sd038_etoro_baseline_reconcile import (
    PreflightError, attempts_consumed, load_local_credentials, run_once,
)
from sidedeck.infrastructure.etoro_demo_client import EtoroDemoAccessError
from sidedeck.infrastructure.etoro_demo_store import EtoroDemoStore

IDS = (710011, 710012, 710013, 710014)


def row(position_id, *, instrument=4101, units=2, **changes):
    data = {"positionID": position_id, "instrumentID": instrument, "orderID": position_id + 5000,
            "isBuy": True, "units": units, "amount": 300, "leverage": 1,
            "openDateTime": "2026-09-01T14:30:00Z", "unrealizedPnL": {"pnL": 1.5}}
    data.update(changes)
    return data


def payload(rows, mirrors=()):
    return {"clientPortfolio": {"positions": list(rows), "credit": 1000, "bonusCredit": 0,
                                "accountCurrencyId": 1, "mirrors": list(mirrors), "orders": [],
                                "ordersForOpen": [], "ordersForClose": [],
                                "ordersForCloseMultiple": [], "entryOrders": [], "exitOrders": [],
                                "stockOrders": []}}


BASE_ROWS = [row(i) for i in IDS]


class FakeClient:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.calls = response, error, 0

    def read_demo_portfolio(self):
        self.calls += 1
        if self.error:
            raise self.error
        return self.response, "request-id"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("ETORO_API_KEY", "test-api-key-value")
    monkeypatch.setenv("ETORO_USER_KEY", "test-user-key-value")
    db = tmp_path / "etoro_demo.sqlite3"
    EtoroDemoStore(str(db)).capture_baseline(payload(BASE_ROWS),
                                             observed_at=datetime.now(timezone.utc),
                                             expected_positions=4)
    return {"db": str(db), "budget": str(tmp_path / "budget.sqlite3"), "bytes": db.read_bytes()}


def go(env, client):
    return run_once(db_path=env["db"], budget_path=env["budget"],
                    client_factory=lambda a, u: client)


def assert_sanitized(result):
    text = json.dumps(result)
    for value in (*[str(i) for i in IDS], "test-api-key-value", "test-user-key-value", "1000",
                  "request-id"):
        assert value not in text
    assert result["etoro_demo_execution_release"] == "NO_GO"
    assert result["broker_execution"] == "DISABLED" and result["orders_submitted"] == 0


def test_matched_baseline(env):
    client = FakeClient(payload(BASE_ROWS))
    result = go(env, client)
    assert result["status"] == "MATCHED" and result["protected_baseline_matched"] == 4
    assert result["current_position_count"] == 4 and not result["mirror_positions_present"]
    assert result["baseline_db_unchanged"] and client.calls == 1
    assert attempts_consumed(env["budget"]) == 1
    assert_sanitized(result)


@pytest.mark.parametrize("rows,matched", [
    (BASE_ROWS[:3], 3),                                           # one baseline closed
    ([*BASE_ROWS[:3], row(IDS[3], units=1)], 3),                  # quantity changed
    ([*BASE_ROWS[:3], row(IDS[3], instrument=4102)], 3),          # instrument changed
])
def test_missing_or_modified_baseline_is_a_discrepancy(env, rows, matched):
    result = go(env, FakeClient(payload(rows)))
    assert result["status"] == "DISCREPANCY" and result["protected_baseline_matched"] == matched
    assert result["baseline_db_unchanged"]
    assert_sanitized(result)


def test_extra_same_instrument_position_stays_unattributed(env):
    result = go(env, FakeClient(payload([*BASE_ROWS, row(720001)])))
    assert result["status"] == "DISCREPANCY"
    assert result["unattributed_extra_positions"] == 1
    assert result["sidedeck_attributed_positions"] == 0


def test_mirror_positions_flagged(env):
    result = go(env, FakeClient(payload([*BASE_ROWS, row(720002, mirrorID=33)])))
    assert result["mirror_positions_present"] and result["status"] == "DISCREPANCY"


def test_mirror_collection_flagged(env):
    result = go(env, FakeClient(payload(BASE_ROWS, mirrors=[{"mirrorID": 1}])))
    assert result["mirror_positions_present"] and result["status"] == "DISCREPANCY"


@pytest.mark.parametrize("bad", [
    {"unexpected": True},
    payload([{**BASE_ROWS[0], "units": "2"}, *BASE_ROWS[1:]]),
])
def test_malformed_response_fails_unverified_without_retry(env, bad):
    client = FakeClient(bad)
    result = go(env, client)
    assert result["status"] == "FAILED_UNVERIFIED" and result["schema_validation"] == "FAILED"
    assert client.calls == 1 and result["baseline_db_unchanged"]
    assert_sanitized(result)


def test_access_error_is_sanitized_and_consumes_the_attempt(env):
    client = FakeClient(error=EtoroDemoAccessError("AUTH_REJECTED", http_status=401))
    result = go(env, client)
    assert result["status"] == "FAILED_UNVERIFIED" and result["http_status"] == 401
    assert client.calls == 1 and attempts_consumed(env["budget"]) == 1
    with pytest.raises(PreflightError, match="exhausted"):
        go(env, FakeClient(payload(BASE_ROWS)))


def test_duplicate_authorization_never_sends_a_second_request(env):
    go(env, FakeClient(payload(BASE_ROWS)))
    second = FakeClient(payload(BASE_ROWS))
    with pytest.raises(PreflightError, match="exhausted"):
        go(env, second)
    assert second.calls == 0 and attempts_consumed(env["budget"]) == 1


def test_missing_or_wrong_baseline_db_refuses_before_reserving(tmp_path, env):
    client = FakeClient(payload(BASE_ROWS))
    with pytest.raises(PreflightError, match="missing"):
        run_once(db_path=str(tmp_path / "absent.sqlite3"), budget_path=env["budget"],
                 client_factory=lambda a, u: client)
    three = tmp_path / "three.sqlite3"
    EtoroDemoStore(str(three)).capture_baseline(payload(BASE_ROWS[:3]),
                                                observed_at=datetime.now(timezone.utc),
                                                expected_positions=3)
    with pytest.raises(PreflightError, match="ambiguous|four"):
        run_once(db_path=str(three), budget_path=env["budget"], client_factory=lambda a, u: client)
    empty = tmp_path / "empty.sqlite3"
    empty.write_bytes(b"")
    with pytest.raises(PreflightError):
        run_once(db_path=str(empty), budget_path=env["budget"], client_factory=lambda a, u: client)
    assert client.calls == 0 and attempts_consumed(env["budget"]) == 0


def test_missing_credentials_refuse_before_reserving(env, monkeypatch):
    monkeypatch.delenv("ETORO_API_KEY")
    client = FakeClient(payload(BASE_ROWS))
    with pytest.raises(PreflightError, match="not available"):
        go(env, client)
    assert client.calls == 0 and attempts_consumed(env["budget"]) == 0


def test_baseline_db_is_byte_identical_after_any_outcome(env):
    go(env, FakeClient(payload(BASE_ROWS[:2])))
    with open(env["db"], "rb") as handle:
        assert handle.read() == env["bytes"]


def test_credential_loader_only_loads_the_two_names(tmp_path, monkeypatch):
    for name in ("ETORO_API_KEY", "ETORO_USER_KEY", "ALPACA_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    dotenv = tmp_path / ".env"
    dotenv.write_text("ETORO_API_KEY=a\nETORO_USER_KEY='b'\nALPACA_API_KEY=c\n", encoding="utf-8")
    load_local_credentials(str(dotenv))
    assert os.environ["ETORO_API_KEY"] == "a" and os.environ["ETORO_USER_KEY"] == "b"
    assert "ALPACA_API_KEY" not in os.environ


def test_cli_requires_explicit_flag(capsys):
    with pytest.raises(SystemExit):
        sd038.main([])
    assert "nothing sent" in capsys.readouterr().err
