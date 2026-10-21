"""SD-042 credential roles and SD-043 sanitized response-shape diagnostics (offline)."""
import json
import uuid
from decimal import Decimal

import pytest

from sidedeck.application.sd036_etoro_demo_desk import OfflineEtoroDemoSimulator
from sidedeck.application.sd042_etoro_credential_roles import (
    CredentialRoleError, assess_roles, require_separated_execution_credentials,
)
from sidedeck.domain.etoro_demo_orders import (
    DEMO_OPEN_PATH, DEMO_ORDER_LOOKUP_PATH, DemoOpenRequest, response_shape_issues,
)

MONITOR = {"ETORO_API_KEY": "app-key-111", "ETORO_USER_KEY": "monitor-user-222"}
TRADE = {"ETORO_DEMO_TRADE_API_KEY": "app-key-111", "ETORO_DEMO_TRADE_USER_KEY": "trade-user-333"}


@pytest.mark.parametrize("env,expected", [
    (MONITOR, "EXECUTION_CREDENTIAL_NOT_CONFIGURED"),
    ({**MONITOR, **TRADE, "ETORO_DEMO_TRADE_USER_KEY": "monitor-user-222"}, "SHARED_REFUSED"),
    ({**MONITOR, **TRADE, "ETORO_DEMO_TRADE_USER_KEY": " monitor-user-222 "}, "SHARED_REFUSED"),
    (TRADE, "MONITOR_CREDENTIAL_NOT_CONFIGURED"),
    ({**MONITOR, **TRADE}, "SEPARATED_PERMISSIONS_UNVERIFIED"),
])
def test_role_separation(env, expected):
    status = assess_roles(env)
    assert status["separation"] == expected
    assert status["execution_release"] == "NO_GO"
    assert "R9_MONITORING_KEY_IS_READ_WRITE" in status["warnings"]
    text = json.dumps(status)
    assert not any(v.strip() in text for v in env.values())


def test_execution_gate_refuses_shared_or_missing_roles():
    with pytest.raises(CredentialRoleError, match="NOT_CONFIGURED"):
        require_separated_execution_credentials(MONITOR)
    with pytest.raises(CredentialRoleError, match="SHARED"):
        require_separated_execution_credentials(
            {**MONITOR, **TRADE, "ETORO_DEMO_TRADE_USER_KEY": "monitor-user-222"})
    require_separated_execution_credentials({**MONITOR, **TRADE})


def test_owner_record_marks_ip_and_expiry_unverified():
    record = assess_roles(MONITOR)["monitor_key_owner_record"]
    assert record["environment"] == "DEMO" and record["permission"] == "READ_WRITE"
    assert record["ip_whitelist"] == "UNVERIFIED" and record["expiry"] == "UNVERIFIED"


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
