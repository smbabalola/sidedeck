"""SD-042 single Demo credential policy and SD-043 response-shape diagnostics (offline)."""
import ast
import inspect
import json
import uuid
from decimal import Decimal

import pytest

from sidedeck.application import etoro_demo_portfolio, p5_demo_refresh
from sidedeck.application.sd036_etoro_demo_desk import OfflineEtoroDemoSimulator
from sidedeck.application.sd042_etoro_credential_roles import (
    POLICY, CredentialRoleError, assess_roles, monitoring_credentials,
    require_execution_credentials,
)
from sidedeck.domain.etoro_demo_orders import (
    DEMO_OPEN_PATH, DEMO_ORDER_LOOKUP_PATH, DemoOpenRequest, response_shape_issues,
)
from sidedeck.infrastructure import etoro_demo_client
from sidedeck.infrastructure.etoro_demo_client import EtoroDemoReadClient

PAIR = {"ETORO_DEMO_TRADE_API_KEY": "app-key-111", "ETORO_DEMO_TRADE_USER_KEY": "demo-user-222"}


@pytest.mark.parametrize("env,expected", [
    (PAIR, POLICY),
    ({}, "DEMO_CREDENTIAL_NOT_CONFIGURED"),
    ({"ETORO_DEMO_TRADE_API_KEY": "app-key-111"}, "DEMO_CREDENTIAL_NOT_CONFIGURED"),
    ({**PAIR, "ETORO_DEMO_TRADE_USER_KEY": "   "}, "DEMO_CREDENTIAL_NOT_CONFIGURED"),
    ({**PAIR, "ETORO_API_KEY": "app-key-111", "ETORO_USER_KEY": "demo-user-222"},
     "EXTRA_CREDENTIAL_NAMES_REFUSED"),
    ({**PAIR, "ETORO_USER_KEY": "other-user"}, "EXTRA_CREDENTIAL_NAMES_REFUSED"),
])
def test_single_pair_policy(env, expected):
    status = assess_roles(env)
    assert status["status"] == expected and status["policy"] == POLICY
    assert status["execution_release"] == "NO_GO"
    assert status["accepted_risks"] == ["R9_SHARED_DEMO_READ_WRITE_PAIR_OWNER_ACCEPTED"]
    assert "MONITORING_GET_ONLY_SINGLE_PATH" in status["compensating_controls"]
    text = json.dumps(status)
    assert not any(v.strip() and v.strip() in text for v in env.values())


def test_monitoring_and_execution_share_only_the_accepted_pair():
    assert monitoring_credentials(PAIR) == ("app-key-111", "demo-user-222")
    require_execution_credentials(PAIR)
    for bad in ({}, {**PAIR, "ETORO_API_KEY": "x"}):
        with pytest.raises(CredentialRoleError, match="refused"):
            monitoring_credentials(bad)
        with pytest.raises(CredentialRoleError, match="refused"):
            require_execution_credentials(bad)


def test_owner_record_and_controls():
    status = assess_roles(PAIR)
    record = status["owner_key_record"]
    assert record["environment"] == "DEMO" and record["permission"] == "READ_WRITE"
    assert record["ip_whitelist"] == "OWNER_ATTESTED" and record["expiry"] == "OWNER_ATTESTED"
    assert "REAL_ROUTES_PERMANENTLY_REFUSED" in status["compensating_controls"]


def test_write_capable_pair_reaches_monitoring_only_through_get_only_client(monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("network must not be touched")

    monkeypatch.setattr(etoro_demo_client, "build_opener", no_network)
    client = EtoroDemoReadClient(*(), api_key=monitoring_credentials(PAIR)[0],
                                 user_key=monitoring_credentials(PAIR)[1])
    for path in ("/api/v2/trading/execution/demo/orders",
                 "/api/v1/trading/execution/demo/market-close-orders/positions/5",
                 "/api/v2/trading/execution/orders", "/api/v1/trading/info/real/pnl"):
        with pytest.raises(PermissionError):
            client._get(path)
    assert "demo-user-222" not in repr(client)
    for module in (etoro_demo_portfolio, p5_demo_refresh):
        tree = ast.parse(inspect.getsource(module))
        called = {n.func.attr for n in ast.walk(tree)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        assert "read_demo_portfolio" in called
        assert not called & {"submit_open", "submit_close", "send", "post", "delete"}
        assert "ETORO_API_KEY" not in inspect.getsource(module)


def test_monitoring_cli_refuses_legacy_names_without_network(monkeypatch, tmp_path, capsys):
    def no_network(*args, **kwargs):
        raise AssertionError("network must not be touched")

    monkeypatch.setattr(etoro_demo_client, "build_opener", no_network)
    for name in ("ETORO_DEMO_TRADE_API_KEY", "ETORO_DEMO_TRADE_USER_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ETORO_API_KEY", "legacy-app")
    monkeypatch.setenv("ETORO_USER_KEY", "legacy-user")
    with pytest.raises(SystemExit):
        etoro_demo_portfolio.main(["--confirm-owner-demo-read", "--db", str(tmp_path / "x.db")])
    err = capsys.readouterr().err
    assert "DEMO_CREDENTIAL_NOT_CONFIGURED" in err and "nothing sent" in err
    assert "legacy-user" not in err


def test_simulator_responses_match_documented_shapes():
    sim = OfflineEtoroDemoSimulator(fill_price=Decimal("100"))
    request = DemoOpenRequest(str(uuid.uuid4()), 1001, Decimal("2"), Decimal("101"))
    accepted = sim.send("POST", DEMO_OPEN_PATH, reference_id=request.reference_id,
                        body=request.body())
    assert response_shape_issues("open_acceptance", accepted) == ()
    lookup = sim.send("GET", DEMO_ORDER_LOOKUP_PATH, reference_id=str(uuid.uuid4()),
                      query={"referenceId": request.reference_id})
    assert response_shape_issues("order_lookup", lookup) == ()
    position_id = lookup["positionExecutions"][0]["positionId"]
    closed = sim.send("POST", f"/api/v1/trading/execution/demo/market-close-orders/positions/"
                      f"{position_id}", reference_id=str(uuid.uuid4()),
                      body={"InstrumentID": 1001, "UnitsToDeduct": None})
    assert response_shape_issues("close_acceptance", closed) == ()
    info = sim.send("GET", f"/api/v1/trading/info/demo/close-orders/"
                    f"{closed['orderForClose']['orderID']}", reference_id=str(uuid.uuid4()))
    assert response_shape_issues("close_info", info) == ()


def test_casing_drift_and_type_drift_reported_without_values():
    drifted = {"orderID": 987654, "action": "open", "transaction": "buy",
               "status": {"id": "3", "errorCode": 0},
               "asset": {"instrumentId": 1001, "leverage": 1, "side": "long"},
               "positionExecutions": [{"positionID": 123456, "state": "open",
                                       "remainingUnits": True,
                                       "openingData": {"orderId": 987654, "units": 2,
                                                       "avgPrice": 100.5, "fees": 0}}]}
    issues = response_shape_issues("order_lookup", drifted)
    assert "orderId: missing (casing differs)" in issues
    assert "status.id: expected int, got str" in issues
    assert "positionExecutions[0].positionId: missing (casing differs)" in issues
    assert "positionExecutions[0].remainingUnits: expected number, got bool" in issues
    assert not any(value in " ".join(issues) for value in ("987654", "123456", "100.5"))


def test_non_object_payloads_reported():
    assert response_shape_issues("close_info", []) == ("$: expected object, got list",)
    assert response_shape_issues("close_info", {"orderID": 1, "statusID": 3, "positions": {}}) \
        == ("positions: expected list, got object",)
