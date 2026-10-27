from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from sidedeck.domain.etoro_demo_books import OrderAttribution, reconcile_demo
from sidedeck.domain.etoro_demo_orders import EtoroDemoOrderError
from sidedeck.application.sd137_pnl_recovery import recover_from_pnl
from sidedeck.domain.etoro_demo import parse_demo_portfolio
from sidedeck.domain.etoro_demo_books import TRADINGAGENTS_BOOK, baseline_from
from sidedeck.domain.etoro_demo_orders import DEMO_PNL_PATH

NOW = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)


def row(pid, oid):
    return {"positionID": pid, "instrumentID": 101, "orderID": oid,
            "isBuy": True, "units": 1, "amount": 10, "leverage": 1,
            "openRate": 10,
            "openDateTime": "2026-10-27T11:00:00Z",
            "unrealizedPnL": {"pnL": 0}}


def body(rows, pending=()):
    return {"clientPortfolio": {
        "credit": 1000, "bonusCredit": 0, "accountCurrencyId": 1,
        "positions": list(rows), "mirrors": [], "orders": list(pending),
        "ordersForOpen": [], "ordersForClose": [], "ordersForCloseMultiple": [],
        "entryOrders": [], "exitOrders": [], "stockOrders": [],
    }}


BASE = tuple(row(i, 9000 + i) for i in range(1, 5))
BASELINE = baseline_from(parse_demo_portfolio(body(BASE), observed_at=NOW))


class Authority:
    def __init__(self, error=None):
        self.error, self.calls = error, []

    def authorize_request(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(grant_id="test-grant")


class Route:
    def __init__(self, response):
        self.response, self.calls = response, []

    def send(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        return self.response


class Desk:
    def __init__(self):
        self.state = "ACCEPTED"
        self.recovered = []

    def accepted_open_snapshot_identity(self, reference_id):
        if reference_id != "open-1" or self.state != "ACCEPTED":
            raise EtoroDemoOrderError("not accepted")
        return {"order_id": 7001}

    def recover_open_from_snapshot(self, reference_id, *, snapshot, now):
        assert reference_id == "open-1"
        self.recovered.append(snapshot)
        report = reconcile_demo(snapshot, baseline=BASELINE,
                                attributions=(OrderAttribution(7001, TRADINGAGENTS_BOOK),),
                                now=now)
        positions = [p for p in snapshot.positions if p.order_id == 7001]
        if (report.status != "MATCHED" or snapshot.pending_orders or len(positions) != 1
                or positions[0].instrument_id != 101 or not positions[0].is_buy
                or positions[0].leverage != 1 or positions[0].units != 1
                or positions[0].open_rate != 10):
            self.state = "HALTED_UNRESOLVED"
            raise EtoroDemoOrderError("recovery requires operator investigation")
        self.state = "RECONCILED_FILLED_BY_SNAPSHOT"
        return positions[0]


def run(route, authority, rows, tmp_path, **changes):
    route.response = body(rows, changes.get("pending", ()))
    desk = Desk()
    result = recover_from_pnl(
        route=route, authority=authority, document={"signed": True}, signature="sig",
        subject_digest="a" * 64, reference_id="unique-read-1",
        open_reference_id="open-1", desk=desk, now=NOW,
    )
    return result, desk


def test_signed_read_recovers_only_exact_order_position(tmp_path):
    route, auth = Route(None), Authority()
    result, desk = run(route, auth, [*BASE, row(55, 7001)], tmp_path)
    assert result.classification == "OWNED_POSITION" and result.position_id == 55
    assert desk.state == "RECONCILED_FILLED_BY_SNAPSHOT" and len(desk.recovered) == 1
    assert auth.calls[0]["write"] is False
    assert route.calls == [("GET", DEMO_PNL_PATH, {"reference_id": "unique-read-1"})]


def test_missing_accepted_order_position_stays_unresolved(tmp_path):
    result, desk = run(Route(None), Authority(), BASE, tmp_path)
    assert result.classification == "UNRESOLVED" and result.position_id is None
    assert desk.state == "HALTED_UNRESOLVED"


@pytest.mark.parametrize("rows,pending", [
    ([*BASE, row(55, 7001), row(56, 7002)], ()),
    ([*BASE, row(55, 7001)], ({"orderID": 8001, "amount": 10},)),
    ([*BASE[1:], row(55, 7001)], ()),
])
def test_partial_foreign_or_pending_snapshot_stays_unresolved(rows, pending, tmp_path):
    result, desk = run(Route(None), Authority(), rows, tmp_path, pending=pending)
    assert result.classification == "UNRESOLVED"
    assert desk.state == "HALTED_UNRESOLVED"


def test_refused_signed_budget_sends_no_read(tmp_path):
    route, auth = Route(None), Authority(PermissionError("budget exhausted"))
    with pytest.raises(PermissionError):
        run(route, auth, BASE, tmp_path)
    assert len(auth.calls) == 1 and route.calls == []
