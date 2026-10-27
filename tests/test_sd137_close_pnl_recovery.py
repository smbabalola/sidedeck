"""SD-137 signed UNKNOWN CLOSE recovery: offline GET-only tests, no credentials/network."""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from sidedeck.application.sd137_pnl_recovery import (
    PnlRecoveryRefused, recover_close_from_pnl,
)
from sidedeck.domain.etoro_demo_books import EtoroDemoBookError
from sidedeck.domain.etoro_demo_orders import DEMO_PNL_PATH

NOW = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)


def body():
    return {"clientPortfolio": {
        "credit": 1000, "bonusCredit": 0, "accountCurrencyId": 1,
        "positions": [], "mirrors": [], "orders": [], "ordersForOpen": [],
        "ordersForClose": [], "ordersForCloseMultiple": [],
        "entryOrders": [], "exitOrders": [], "stockOrders": [],
    }}


class Authority:
    def __init__(self, error=None):
        self.error, self.calls = error, []

    def authorize_request(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(grant_id="signed-read-once")


class Route:
    def __init__(self, payload=None):
        self.payload = body() if payload is None else payload
        self.calls = []

    def send(self, method, path, *, reference_id, **kwargs):
        self.calls.append((method, path, reference_id))
        return self.payload


class Desk:
    def __init__(self, *, row=None, state="RECONCILED_CLOSED_BY_SNAPSHOT", error=None):
        self.row = row if row is not None else {
            "kind": "CLOSE", "state": "OUTCOME_UNKNOWN",
            "position_id": 55, "order_id": None,
        }
        self.state, self.error, self.preflights, self.recovered = state, error, [], []

    def unknown_close_snapshot_identity(self, close_reference_id):
        self.preflights.append(close_reference_id)
        if close_reference_id != "unknown-close" or self.error:
            raise EtoroDemoBookError("unknown close has no SideDeck ownership")
        return self.row

    def recover_close_from_snapshot(self, reference_id, *, snapshot, now):
        assert reference_id == "unknown-close" and now == NOW
        self.recovered.append(snapshot)
        if self.state == "RAISE":
            raise EtoroDemoBookError("broker account mismatch")
        return self.state


def recover(route=None, authority=None, desk=None, **changes):
    return recover_close_from_pnl(
        route=route if route is not None else Route(),
        authority=authority if authority is not None else Authority(),
        desk=desk if desk is not None else Desk(),
        document={"signed": True}, signature="owner-sig",
        subject_digest="a" * 64,
        reference_id="unique-read-once", close_reference_id="unknown-close",
        now=changes.pop("now", NOW), **changes,
    )


@pytest.mark.parametrize("state,classification", [
    ("RECONCILED_NOT_EXECUTED", "NO_REDUCTION_OBSERVED"),
    ("RECONCILED_PARTIAL_BY_SNAPSHOT", "POSITION_REDUCED_EXECUTOR_UNVERIFIED"),
    ("RECONCILED_CLOSED_BY_SNAPSHOT", "POSITION_ABSENT_EXECUTOR_UNVERIFIED"),
    ("RAISE", "UNRESOLVED"),
])
def test_one_signed_read_never_claims_close_execution_or_realised_pnl(state, classification):
    route, authority, desk = Route(), Authority(), Desk(state=state)
    result = recover(route=route, authority=authority, desk=desk)
    assert result.classification == classification
    assert result.realised_pnl_status == "UNVERIFIED_BROKER_CLOSE_EXECUTION_AND_PRICE"
    assert result.position_id == 55 and result.close_order_id is None
    assert result.grant_id == "signed-read-once"
    assert desk.preflights == ["unknown-close"]
    assert len(desk.recovered) == 1
    assert authority.calls[0]["write"] is False
    assert route.calls == [("GET", DEMO_PNL_PATH, "unique-read-once")]


def test_durable_preflight_refuses_before_grant_or_get():
    route, authority = Route(), Authority()
    with pytest.raises(PnlRecoveryRefused, match="SideDeck-owned"):
        recover(route=route, authority=authority, desk=Desk(error=True))
    assert authority.calls == [] and route.calls == []


def test_signed_budget_refused_before_get_and_lineage_mutation():
    route, authority, desk = Route(), Authority(PermissionError("expired")), Desk()
    with pytest.raises(PermissionError, match="expired"):
        recover(route=route, authority=authority, desk=desk)
    assert len(authority.calls) == 1 and route.calls == []
    assert desk.recovered == []


def test_malformed_broker_response_does_not_reconcile_state():
    route, desk = Route({"clientPortfolio": {}}), Desk()
    with pytest.raises(ValueError):
        recover(route=route, desk=desk)
    assert len(route.calls) == 1 and desk.recovered == []


def test_missing_and_naive_identity_refused_before_get():
    route, auth = Route(), Authority()
    with pytest.raises(PnlRecoveryRefused, match="identity"):
        recover_close_from_pnl(
            route=route, authority=auth, desk=Desk(),
            document={}, signature="sig", subject_digest="a" * 64,
            reference_id="", close_reference_id="unknown-close", now=NOW,
        )
    with pytest.raises(PnlRecoveryRefused, match="timezone-aware"):
        recover(route=route, authority=auth, desk=Desk(),
                now=datetime(2026, 10, 27, 12))
    assert route.calls == [] and auth.calls == []
