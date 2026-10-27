"""SD-137 durable close protection with offline fake HTTP; no eToro contact."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from sidedeck.application.sd036_etoro_demo_desk import (
    EtoroDemoLineage, TransportOutcomeUnknown,
)
from sidedeck.application.sd129_etoro_demo_order_port import (
    DemoLineageRefused, EtoroDemoOrderPort,
)
from sidedeck.domain.etoro_demo_orders import (
    DEMO_CLOSE_INFO_PATH, DemoCloseRequest, DemoOpenRequest, EtoroDemoOrderError,
    CloseAcceptance, require_demo_route,
)

OPEN_ID = "11111111-1111-4111-8111-111111111111"
CLOSE_ID = "22222222-2222-4222-8222-222222222222"
SECOND_CLOSE_ID = "33333333-3333-4333-8333-333333333333"
BOOK = "etoro-demo:tradingagents"


class FakeRoute:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, str]] = []

    def send(self, method: str, path: str, *, reference_id: str,
             body: dict[str, Any] | None = None,
             query: dict[str, str] | None = None) -> Any:
        require_demo_route(method, path)
        self.calls.append((method, path, reference_id))
        if not self.responses:
            raise AssertionError("extra broker I/O")
        reply = self.responses.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def store(path: Path) -> EtoroDemoLineage:
    return EtoroDemoLineage(str(path), baseline_position_ids=[900001],
                            baseline_order_ids=[900002])


def open_request() -> DemoOpenRequest:
    return DemoOpenRequest(OPEN_ID, 1004, Decimal("0.09"), Decimal("110"))


def close_request(reference: str = CLOSE_ID) -> DemoCloseRequest:
    return DemoCloseRequest(reference, 100001, 1004)


def opening() -> dict[str, Any]:
    return {"referenceId": OPEN_ID, "orderId": 101}


def open_lookup() -> dict[str, Any]:
    return {
        "orderId": 101, "action": "open", "transaction": "buy",
        "status": {"id": 3, "errorCode": 0},
        "asset": {"instrumentId": 1004, "leverage": 1, "side": "long"},
        "positionExecutions": [{
            "positionId": 100001, "state": "open", "remainingUnits": 0.09,
            "openingData": {
                "orderId": 101, "units": 0.09, "avgPrice": 105.0, "fees": 0.0,
            },
        }],
    }


def close_accepted() -> dict[str, Any]:
    return {"orderForClose": {
        "orderID": 202, "positionID": 100001, "instrumentID": 1004,
    }}


def close_info() -> dict[str, Any]:
    return {"orderID": 202, "statusID": 3,
            "positions": [{"positionID": 100001, "units": 0.09}]}


def open_and_lookup(db: EtoroDemoLineage, replies: list[Any]) -> tuple[
    EtoroDemoOrderPort, FakeRoute, Any,
]:
    route = FakeRoute([opening(), open_lookup(), *replies])
    port = EtoroDemoOrderPort(route, lineage=db)
    port.submit_open(open_request(), intent_id="intent-open", book_id=BOOK)
    _, owner = port.lookup_open(open_request())
    assert owner is not None
    return port, route, owner


def test_accepted_close_info_can_be_read_after_restart_without_post(
    tmp_path: Path,
) -> None:
    path = tmp_path / "lineage.sqlite3"
    first = store(path)
    port, route, owner = open_and_lookup(first, [close_accepted()])
    receipt = port.submit_owned_close(close_request(), owner=owner,
                                      intent_id="intent-close", book_id=BOOK)
    assert receipt == CloseAcceptance(202, 100001)
    assert [method for method, _, _ in route.calls] == ["POST", "GET", "POST"]
    assert first.order(CLOSE_ID)["order_id"] == 202
    first.close()

    second = store(path)
    reader = FakeRoute([close_info()])
    result = EtoroDemoOrderPort(reader, lineage=second).recover_close_info(
        receipt, request=close_request(),
    )
    assert result.position_status == (
        "BROKER_REPORTS_FULL_CLOSE_PENDING_PORTFOLIO_RECONCILIATION")
    assert result.realised_pnl_status == "UNAVAILABLE_WITHOUT_BROKER_CLOSE_PRICE"
    assert reader.calls == [
        ("GET", DEMO_CLOSE_INFO_PATH.format(order_id=202),
         "close-recovery:" + CLOSE_ID),
    ]
    second.close()


def test_unknown_close_post_is_one_shot_even_after_process_restart(
    tmp_path: Path,
) -> None:
    path = tmp_path / "lineage.sqlite3"
    first = store(path)
    port, _, owner = open_and_lookup(
        first, [TransportOutcomeUnknown("response lost")])
    with pytest.raises(TransportOutcomeUnknown):
        port.submit_owned_close(close_request(), owner=owner,
                                intent_id="intent-close", book_id=BOOK)
    assert first.order(CLOSE_ID)["state"] == "PENDING_SUBMIT"
    first.close()

    second = store(path)
    fake = FakeRoute([open_lookup()])
    restarted = EtoroDemoOrderPort(fake, lineage=second)
    _, current = restarted.lookup_open(open_request())
    assert current is not None
    with pytest.raises(EtoroDemoOrderError):
        restarted.submit_owned_close(
            close_request(SECOND_CLOSE_ID), owner=current,
            intent_id="intent-close-2", book_id=BOOK,
        )
    assert [method for method, _, _ in fake.calls] == ["GET"]
    second.close()


def test_two_independent_workers_cannot_reserve_duplicate_unresolved_close(
    tmp_path: Path,
) -> None:
    path = tmp_path / "lineage.sqlite3"
    first = store(path)
    port, _, owner = open_and_lookup(first, [close_accepted()])
    second = store(path)
    route = FakeRoute([open_lookup()])
    other = EtoroDemoOrderPort(route, lineage=second)
    _, current = other.lookup_open(open_request())
    assert current is not None
    port.submit_owned_close(close_request(), owner=owner,
                            intent_id="intent-close", book_id=BOOK)
    with pytest.raises(EtoroDemoOrderError):
        other.submit_owned_close(
            close_request(SECOND_CLOSE_ID), owner=current,
            intent_id="intent-close-2", book_id=BOOK,
        )
    assert [method for method, _, _ in route.calls] == ["GET"]
    first.close()
    second.close()


def test_forged_durable_close_acceptance_rejected_before_get(
    tmp_path: Path,
) -> None:
    lineage = store(tmp_path / "lineage.sqlite3")
    port, _, owner = open_and_lookup(lineage, [close_accepted()])
    receipt = port.submit_owned_close(close_request(), owner=owner,
                                      intent_id="intent-close", book_id=BOOK)
    fake = FakeRoute([])
    reader = EtoroDemoOrderPort(fake, lineage=lineage)
    with pytest.raises(DemoLineageRefused, match="inconsistent"):
        reader.recover_close_info(
            CloseAcceptance(receipt.order_id + 1, receipt.position_id),
            request=close_request(),
        )
    assert fake.calls == []
    lineage.close()


def test_unbound_port_cannot_invent_durable_close_authority() -> None:
    fake = FakeRoute([])
    with pytest.raises(DemoLineageRefused, match="persisted lineage"):
        EtoroDemoOrderPort(fake).recover_close_info(
            CloseAcceptance(202, 100001), request=close_request(),
        )
    assert fake.calls == []
