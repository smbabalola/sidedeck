"""SD-137 offline durable open recovery: no credentials, network or Demo orders."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from sidedeck.application.sd036_etoro_demo_desk import (
    EtoroDemoLineage, TransportNotFound, TransportOutcomeUnknown,
)
from sidedeck.application.sd129_etoro_demo_order_port import (
    DemoLineageRefused, EtoroDemoOrderPort,
)
from sidedeck.domain.etoro_demo_books import EtoroDemoBookError
from sidedeck.domain.etoro_demo_orders import (
    DEMO_OPEN_PATH, DEMO_ORDER_LOOKUP_PATH,
    DemoOpenRequest, EtoroDemoOrderError, OpenAcceptance, require_demo_route,
)

REF = "11111111-1111-4111-8111-111111111111"
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
            raise AssertionError("unexpected request")
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def open_request() -> DemoOpenRequest:
    return DemoOpenRequest(REF, 1004, Decimal("0.09"), Decimal("110"))


def accepted() -> dict[str, Any]:
    return {"referenceId": REF, "orderId": 101}


def lookup(*, position: int = 100001) -> dict[str, Any]:
    return {
        "orderId": 101, "action": "open", "transaction": "buy",
        "status": {"id": 3, "errorCode": 0},
        "asset": {"instrumentId": 1004, "leverage": 1, "side": "long"},
        "positionExecutions": [{
            "positionId": position, "state": "open", "remainingUnits": 0.09,
            "openingData": {
                "orderId": 101, "units": 0.09, "avgPrice": 105.0, "fees": 0.0,
            },
        }],
    }


def store(path: Path) -> EtoroDemoLineage:
    return EtoroDemoLineage(str(path),
                            baseline_position_ids=[900001],
                            baseline_order_ids=[900002])


def test_persisted_acceptance_recovers_after_restart_with_get_only(tmp_path: Path) -> None:
    db = tmp_path / "lineage.sqlite3"
    first = store(db)
    sent = FakeRoute([accepted()])
    proof = EtoroDemoOrderPort(sent, lineage=first).submit_open(
        open_request(), intent_id="intent-1", book_id=BOOK,
    )
    assert proof == OpenAcceptance(101, REF)
    first.close()

    restarted = store(db)
    queried = FakeRoute([TransportNotFound("eventual-consistency 404"), lookup()])
    port = EtoroDemoOrderPort(queried, lineage=restarted)
    result = port.recover_accepted_open(
        open_request(), proof,
        wait_before_first_lookup=lambda: None,
        wait_before_order_id_fallback=lambda: None,
    )
    assert result.classification == "BROKER_CONFIRMED_OPEN"
    assert result.requests_used == 2
    assert result.position is not None and result.position.position_id == 100001
    assert [method for method, _, _ in queried.calls] == ["GET", "GET"]
    assert queried.calls[0][1] == DEMO_ORDER_LOOKUP_PATH
    assert restarted.order(REF)["order_id"] == 101
    assert restarted.owned(100001)["reference_id"] == REF
    restarted.close()


def test_two_processes_cannot_repeat_same_reserved_open(tmp_path: Path) -> None:
    db = tmp_path / "lineage.sqlite3"
    a, b = store(db), store(db)
    original, duplicate = FakeRoute([accepted()]), FakeRoute([])
    EtoroDemoOrderPort(original, lineage=a).submit_open(
        open_request(), intent_id="intent-1", book_id=BOOK,
    )
    with pytest.raises(EtoroDemoOrderError, match="reference or intent already used"):
        EtoroDemoOrderPort(duplicate, lineage=b).submit_open(
            open_request(), intent_id="intent-2", book_id=BOOK,
        )
    assert len(original.calls) == 1 and original.calls[0][0:2] == (
        "POST", DEMO_OPEN_PATH)
    assert duplicate.calls == []
    a.close()
    b.close()


def test_crash_after_unknown_post_preserves_reservation_and_read_only_recovery(
    tmp_path: Path,
) -> None:
    db = tmp_path / "lineage.sqlite3"
    original = store(db)
    first = FakeRoute([TransportOutcomeUnknown("accepted but response lost")])
    with pytest.raises(TransportOutcomeUnknown):
        EtoroDemoOrderPort(first, lineage=original).submit_open(
            open_request(), intent_id="intent-1", book_id=BOOK,
        )
    assert original.order(REF)["state"] == "OUTCOME_UNKNOWN"
    original.close()

    restarted = store(db)
    refused = FakeRoute([])
    with pytest.raises(EtoroDemoOrderError):
        EtoroDemoOrderPort(refused, lineage=restarted).submit_open(
            open_request(), intent_id="intent-1", book_id=BOOK,
        )
    assert refused.calls == []
    lookup_route = FakeRoute([lookup()])
    _, position = EtoroDemoOrderPort(lookup_route, lineage=restarted).lookup_open(
        open_request())
    assert position is not None and position.order_id == 101
    assert [method for method, _, _ in lookup_route.calls] == ["GET"]
    assert restarted.order(REF)["order_id"] == 101
    restarted.close()


def test_forged_recovery_ids_and_changed_request_refused_pre_get(tmp_path: Path) -> None:
    db = tmp_path / "lineage.sqlite3"
    lineage = store(db)
    EtoroDemoOrderPort(FakeRoute([accepted()]), lineage=lineage).submit_open(
        open_request(), intent_id="intent-1", book_id=BOOK,
    )
    fake = FakeRoute([])
    port = EtoroDemoOrderPort(fake, lineage=lineage)
    with pytest.raises(DemoLineageRefused, match="durable validated acceptance"):
        port.recover_accepted_open(
            open_request(), OpenAcceptance(999, REF),
            wait_before_first_lookup=lambda: None,
            wait_before_order_id_fallback=lambda: None,
        )
    altered = DemoOpenRequest(REF, 1004, Decimal("0.08"), Decimal("110"))
    with pytest.raises(DemoLineageRefused, match="durable open identity"):
        port.lookup_open(altered)
    assert fake.calls == []
    lineage.close()


def test_broker_cannot_launder_protected_baseline_position_into_owned(
    tmp_path: Path,
) -> None:
    lineage = store(tmp_path / "lineage.sqlite3")
    EtoroDemoOrderPort(FakeRoute([accepted()]), lineage=lineage).submit_open(
        open_request(), intent_id="intent-1", book_id=BOOK,
    )
    queried = FakeRoute([lookup(position=900001)])
    with pytest.raises(EtoroDemoBookError, match="baseline"):
        EtoroDemoOrderPort(queried, lineage=lineage).lookup_open(open_request())
    assert len(queried.calls) == 1 and queried.calls[0][0] == "GET"
    assert lineage.owned(900001) is None
    lineage.close()
