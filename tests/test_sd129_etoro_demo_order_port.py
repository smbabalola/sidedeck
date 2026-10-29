"""SD-129 strict Demo-only port tests. All transport responses are offline fakes."""
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import Any

import pytest

from sidedeck.application.sd129_etoro_demo_order_port import (
    ConfirmedOpen, DemoLineageRefused, EtoroDemoOrderPort,
)
from sidedeck.domain.etoro_demo_orders import (
    DEMO_CLOSE_INFO_PATH, DEMO_OPEN_PATH, DEMO_ORDER_LOOKUP_PATH,
    DemoCloseRequest, DemoOpenRequest, EtoroDemoOrderError, require_demo_route,
)

_OPEN_ID = "11111111-1111-4111-8111-111111111111"
_CLOSE_ID = "22222222-2222-4222-8222-222222222222"


class _FakeRoute:
    """Captures calls without credentials, sockets or broker network I/O."""

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, str, Any, Any]] = []

    def send(self, method: str, path: str, *, reference_id: str,
             body: dict[str, Any] | None = None,
             query: dict[str, str] | None = None) -> dict[str, Any]:
        require_demo_route(method, path)
        self.calls.append((method, path, reference_id, body, query))
        if not self.responses:
            raise AssertionError("unexpected broker request")
        return self.responses.pop(0)


def _open() -> DemoOpenRequest:
    return DemoOpenRequest(_OPEN_ID, 1004, Decimal("0.09"), Decimal("110"))


def _close(position_id: int = 100001, instrument_id: int = 1004,
           units: Decimal | None = None) -> DemoCloseRequest:
    return DemoCloseRequest(_CLOSE_ID, position_id, instrument_id, units)


def _accepted() -> dict[str, Any]:
    return {"orderId": 101, "referenceId": _OPEN_ID}


def _lookup(*, state: str = "open", status: int = 3, position: int = 100001
            ) -> dict[str, Any]:
    return {
        "orderId": 101, "action": "open", "transaction": "buy",
        "status": {"id": status, "errorCode": 0},
        "asset": {"instrumentId": 1004, "leverage": 1, "side": "long"},
        "positionExecutions": [{
            "positionId": position, "state": state,
            "remainingUnits": 0.09 if state == "open" else 0.0,
            "openingData": {
                "orderId": 101, "units": 0.09, "avgPrice": 105.0, "fees": 0.0,
            },
        }],
    }


def _close_accepted() -> dict[str, Any]:
    return {"orderForClose": {
        "orderID": 202, "positionID": 100001, "instrumentID": 1004,
    }}


def _close_lookup() -> dict[str, Any]:
    return {
        "orderID": 202, "statusID": 3,
        "positions": [{"positionID": 100001, "units": 0.09}],
    }


def test_typed_demo_order_round_trip_is_not_a_pnl_claim() -> None:
    fake = _FakeRoute([_accepted(), _lookup(), _close_accepted(), _close_lookup()])
    port = EtoroDemoOrderPort(fake)
    request = _open()
    acceptance = port.submit_open(request)
    assert acceptance.order_id == 101
    assert len(fake.calls) == 1   # accepted HTTP POST is NOT a fill
    assert fake.calls[0][:2] == ("POST", DEMO_OPEN_PATH)
    assert fake.calls[0][2] == _OPEN_ID
    assert fake.calls[0][3] == request.body()

    outcome, owner = port.lookup_open(request, order_id=acceptance.order_id)
    assert outcome.status == "FILLED"
    assert owner is not None
    assert owner.order_id == 101
    assert owner.position_id == 100001
    assert owner.remaining_units == Decimal("0.09")
    assert fake.calls[1][0:2] == ("GET", DEMO_ORDER_LOOKUP_PATH)
    assert fake.calls[1][4] == {"orderId": "101"}

    close_request = _close(owner.position_id)
    closed = port.submit_owned_close(close_request, owner=owner)
    assert closed.order_id == 202
    assert fake.calls[2][0:2] == ("POST", close_request.path)
    assert fake.calls[2][3] == close_request.body()
    status = port.lookup_close(closed, request=close_request, owner=owner)
    assert status.outcome.closed_units == Decimal("0.09")
    assert status.outcome.status == "FILLED"
    assert status.realised_pnl_status == "UNAVAILABLE_WITHOUT_BROKER_CLOSE_PRICE"
    assert fake.calls[3][0:2] == (
        "GET", DEMO_CLOSE_INFO_PATH.format(order_id=202))
    assert all("/real/" not in path for _, path, *_ in fake.calls)


def test_accepted_post_with_invalid_echo_never_proves_open() -> None:
    fake = _FakeRoute([{"orderId": 101, "referenceId":
                        "33333333-3333-4333-8333-333333333333"}])
    with pytest.raises(EtoroDemoOrderError, match="echo"):
        EtoroDemoOrderPort(fake).submit_open(_open())
    assert len(fake.calls) == 1


def test_order_lookup_by_reference_remains_read_only() -> None:
    fake = _FakeRoute([_lookup()])
    port = EtoroDemoOrderPort(fake)
    outcome, owner = port.lookup_open(_open())
    assert outcome.order_id == 101 and owner is not None
    assert fake.calls == [("GET", DEMO_ORDER_LOOKUP_PATH,
                           "lookup:" + _OPEN_ID, None, {"referenceId": _OPEN_ID})]


def test_closed_manually_does_not_produce_owned_open_position() -> None:
    fake = _FakeRoute([_lookup(state="closed")])
    outcome, owner = EtoroDemoOrderPort(fake).lookup_open(_open(), order_id=101)
    assert outcome.status == "FILLED"
    assert owner is None


def test_nonterminal_order_does_not_prove_a_fill() -> None:
    payload = _lookup(status=2)
    payload["positionExecutions"] = []
    fake = _FakeRoute([payload])
    outcome, owner = EtoroDemoOrderPort(fake).lookup_open(_open(), order_id=101)
    assert outcome.status == "PLACED"
    assert owner is None


def test_multiple_positions_refuse_automatic_ownership() -> None:
    raw = _lookup()
    extra = dict(raw["positionExecutions"][0])
    extra["positionId"] = 100002
    raw["positionExecutions"].append(extra)
    # Two executions of 0.09 would breach the requested 0.09 first; all
    # inconsistent fills must refuse, regardless of which parser finds them.
    with pytest.raises((DemoLineageRefused, EtoroDemoOrderError)):
        EtoroDemoOrderPort(_FakeRoute([raw])).lookup_open(_open(), order_id=101)


def test_protected_or_forged_position_id_cannot_be_closed() -> None:
    fake = _FakeRoute([_lookup()])
    port = EtoroDemoOrderPort(fake)
    _, owner = port.lookup_open(_open(), order_id=101)
    assert owner is not None
    with pytest.raises(DemoLineageRefused):
        port.submit_owned_close(_close(987654321), owner=owner)
    with pytest.raises(DemoLineageRefused):
        port.submit_owned_close(_close(100001, instrument_id=1002), owner=owner)
    with pytest.raises(DemoLineageRefused):
        port.submit_owned_close(_close(units=Decimal("0.01")), owner=owner)
    with pytest.raises(DemoLineageRefused):
        port.submit_owned_close(_close(), owner=replace(owner))
    assert len(fake.calls) == 1  # no new POST


def test_same_position_claimed_from_untrusted_object_never_sends_close() -> None:
    fake = _FakeRoute([])
    made_up = ConfirmedOpen(_open(), 101, 100001, Decimal("0.09"),
                            Decimal("0.09"), Decimal("100"))
    with pytest.raises(DemoLineageRefused):
        EtoroDemoOrderPort(fake).submit_owned_close(_close(), owner=made_up)
    assert fake.calls == []


def test_close_response_mismatch_and_overfill_refused() -> None:
    fake = _FakeRoute([_lookup(), _close_accepted(),
                       {"orderID": 202, "statusID": 3,
                        "positions": [{"positionID": 100001, "units": 0.9}]}])
    port = EtoroDemoOrderPort(fake)
    _, owner = port.lookup_open(_open(), order_id=101)
    assert owner is not None
    request = _close()
    accepted = port.submit_owned_close(request, owner=owner)
    with pytest.raises(EtoroDemoOrderError, match="more units"):
        port.lookup_close(accepted, request=request, owner=owner)
