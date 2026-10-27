"""SD-134: deterministic eToro Demo delayed-lookup/reduce-only safety (NO NETWORK)."""
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import Any

import pytest

from sidedeck.application.sd036_etoro_demo_desk import (
    TransportNotFound, TransportOutcomeUnknown,
)
from sidedeck.application.sd129_etoro_demo_order_port import (
    DemoLineageRefused, EtoroDemoOrderPort,
)
from sidedeck.domain.etoro_demo_orders import (
    DEMO_CLOSE_INFO_PATH, DEMO_OPEN_PATH, DEMO_ORDER_LOOKUP_PATH,
    DemoCloseRequest, DemoOpenRequest, EtoroDemoOrderError, require_demo_route,
)

OPEN_REFERENCE = "11111111-1111-4111-8111-111111111111"
CLOSE_REFERENCE = "22222222-2222-4222-8222-222222222222"


class FakeDemoRoute:
    def __init__(self, replies: list[Any]) -> None:
        self.replies = list(replies)
        self.calls: list[tuple[str, str, Any]] = []

    def send(self, method: str, path: str, *, reference_id: str,
             body: dict[str, Any] | None = None,
             query: dict[str, str] | None = None) -> Any:
        require_demo_route(method, path)
        self.calls.append((method, path, query))
        if not self.replies:
            raise AssertionError("unexpected broker call")
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def request() -> DemoOpenRequest:
    return DemoOpenRequest(OPEN_REFERENCE, 1004, Decimal("0.09"), Decimal("110"))


def accepted() -> dict[str, Any]:
    return {"referenceId": OPEN_REFERENCE, "orderId": 101}


def lookup(*, order_id: int = 101, state: str = "open",
           status_id: int = 3) -> dict[str, Any]:
    executions = [] if status_id in (2, 4, 7, 8) else [{
        "positionId": 100001, "state": state,
        "remainingUnits": 0.09 if state == "open" else 0.0,
        "openingData": {
            "orderId": order_id, "units": 0.09,
            "avgPrice": 105.0, "fees": 0.0,
        },
    }]
    return {
        "orderId": order_id, "action": "open", "transaction": "buy",
        "status": {"id": status_id, "errorCode": 0},
        "asset": {"instrumentId": 1004, "leverage": 1, "side": "long"},
        "positionExecutions": executions,
    }


def close_request() -> DemoCloseRequest:
    return DemoCloseRequest(CLOSE_REFERENCE, 100001, 1004)


def test_reference_404_uses_accepted_order_id_then_proves_position() -> None:
    fake = FakeDemoRoute([
        accepted(), TransportNotFound("broker search returned 404"), lookup(),
    ])
    port = EtoroDemoOrderPort(fake)
    approval = port.submit_open(request())
    paced: list[str] = []
    result = port.recover_accepted_open(
        request(), approval,
        wait_before_first_lookup=lambda: paced.append("wait_after_post"),
        wait_before_order_id_fallback=lambda: paced.append("wait_after_404"),
    )
    assert result.classification == "BROKER_CONFIRMED_OPEN"
    assert result.requests_used == 2
    assert result.position is not None
    assert result.position.position_id == 100001
    assert paced == ["wait_after_post", "wait_after_404"]
    assert fake.calls == [
        ("POST", DEMO_OPEN_PATH, None),
        ("GET", DEMO_ORDER_LOOKUP_PATH, {"referenceId": OPEN_REFERENCE}),
        ("GET", DEMO_ORDER_LOOKUP_PATH, {"orderId": "101"}),
    ]


def test_double_404_preserves_unknown_outcome_and_never_resubmits() -> None:
    fake = FakeDemoRoute([accepted(), TransportNotFound("404"), TransportNotFound("404")])
    port = EtoroDemoOrderPort(fake)
    approval = port.submit_open(request())
    state = port.recover_accepted_open(
        request(), approval, wait_before_first_lookup=lambda: None,
        wait_before_order_id_fallback=lambda: None,
    )
    assert state.classification == "UNRESOLVED_NOT_VISIBLE"
    assert state.requests_used == 2 and state.position is None
    assert len([c for c in fake.calls if c[0] == "POST"]) == 1
    with pytest.raises(DemoLineageRefused, match="already attempted"):
        port.submit_open(request())
    assert len(fake.calls) == 3


def test_order_id_mismatch_from_reference_lookup_never_falls_back() -> None:
    fake = FakeDemoRoute([accepted(), lookup(order_id=555)])
    port = EtoroDemoOrderPort(fake)
    approval = port.submit_open(request())
    with pytest.raises(EtoroDemoOrderError, match="different order"):
        port.recover_accepted_open(
            request(), approval, wait_before_first_lookup=lambda: None,
            wait_before_order_id_fallback=lambda: None,
        )
    assert len(fake.calls) == 2


def test_pending_or_closed_position_never_claimed_safe_to_close() -> None:
    for response in (lookup(status_id=2), lookup(state="closed")):
        fake = FakeDemoRoute([accepted(), response])
        port = EtoroDemoOrderPort(fake)
        approval = port.submit_open(request())
        state = port.recover_accepted_open(
            request(), approval, wait_before_first_lookup=lambda: None,
            wait_before_order_id_fallback=lambda: None,
        )
        assert state.classification == "UNRESOLVED"
        assert state.position is None
        assert len(fake.calls) == 2


def test_terminal_no_fill_does_not_claim_position_or_repeat_open() -> None:
    fake = FakeDemoRoute([accepted(), lookup(status_id=4)])
    port = EtoroDemoOrderPort(fake)
    approval = port.submit_open(request())
    state = port.recover_accepted_open(
        request(), approval, wait_before_first_lookup=lambda: None,
        wait_before_order_id_fallback=lambda: None,
    )
    assert state.classification == "TERMINAL_NO_FILL"
    assert state.position is None and state.requests_used == 1
    with pytest.raises(DemoLineageRefused):
        port.submit_open(request())


def test_recovery_refuses_forged_acceptance_before_any_get() -> None:
    fake = FakeDemoRoute([accepted()])
    port = EtoroDemoOrderPort(fake)
    approval = port.submit_open(request())
    with pytest.raises(DemoLineageRefused, match="validated acceptance"):
        port.recover_accepted_open(
            request(), replace(approval),
            wait_before_first_lookup=lambda: None,
            wait_before_order_id_fallback=lambda: None,
        )
    assert len(fake.calls) == 1


def test_restart_does_not_mint_accepted_order_lineage_from_memory() -> None:
    fake = FakeDemoRoute([])
    second_process = EtoroDemoOrderPort(fake)
    from sidedeck.domain.etoro_demo_orders import OpenAcceptance
    with pytest.raises(DemoLineageRefused, match="validated acceptance"):
        second_process.recover_accepted_open(
            request(), OpenAcceptance(101, OPEN_REFERENCE),
            wait_before_first_lookup=lambda: None,
            wait_before_order_id_fallback=lambda: None,
        )
    assert not fake.calls


def test_failed_open_post_never_resubmits_in_same_process() -> None:
    fake = FakeDemoRoute([TransportOutcomeUnknown("response lost")])
    port = EtoroDemoOrderPort(fake)
    with pytest.raises(TransportOutcomeUnknown):
        port.submit_open(request())
    with pytest.raises(DemoLineageRefused, match="already attempted"):
        port.submit_open(request())
    assert len(fake.calls) == 1


def test_close_may_only_be_submitted_once_even_when_outcome_unknown() -> None:
    fake = FakeDemoRoute([lookup(), TransportOutcomeUnknown("response lost")])
    port = EtoroDemoOrderPort(fake)
    _, owner = port.lookup_open(request(), order_id=101)
    assert owner is not None
    with pytest.raises(TransportOutcomeUnknown):
        port.submit_owned_close(close_request(), owner=owner)
    with pytest.raises(DemoLineageRefused, match="reduce-only"):
        port.submit_owned_close(close_request(), owner=owner)
    assert len([x for x in fake.calls if x[0] == "POST"]) == 1


def test_close_reconciliation_requires_returned_acceptance() -> None:
    close_acceptance = {"orderForClose": {
        "orderID": 202, "positionID": 100001, "instrumentID": 1004,
    }}
    fake = FakeDemoRoute([lookup(), close_acceptance])
    port = EtoroDemoOrderPort(fake)
    _, owner = port.lookup_open(request(), order_id=101)
    assert owner is not None
    receipt = port.submit_owned_close(close_request(), owner=owner)
    with pytest.raises(DemoLineageRefused):
        port.lookup_close(replace(receipt), request=close_request(), owner=owner)
    assert len(fake.calls) == 2


@pytest.mark.parametrize("status_id,units,expected", [
    (3, 0.09, "BROKER_REPORTS_FULL_CLOSE_PENDING_PORTFOLIO_RECONCILIATION"),
    (3, 0.04, "UNRESOLVED_PARTIAL_OR_PENDING"),
    (5, 0.04, "UNRESOLVED_PARTIAL_OR_PENDING"),
    (2, 0.0, "UNRESOLVED_PARTIAL_OR_PENDING"),
    (4, 0.0, "BROKER_REPORTS_NO_CLOSE"),
])
def test_close_info_never_claims_final_broker_settlement(
    status_id: int, units: float, expected: str,
) -> None:
    close_response = {
        "orderID": 202, "statusID": status_id,
        "positions": ([{"positionID": 100001, "units": units}] if units > 0 else []),
    }
    fake = FakeDemoRoute([
        lookup(),
        {"orderForClose": {
            "orderID": 202, "positionID": 100001, "instrumentID": 1004,
        }},
        close_response,
    ])
    port = EtoroDemoOrderPort(fake)
    _, owner = port.lookup_open(request(), order_id=101)
    assert owner is not None
    receipt = port.submit_owned_close(close_request(), owner=owner)
    result = port.lookup_close(receipt, request=close_request(), owner=owner)
    assert result.position_status == expected
    assert result.realised_pnl_status == "UNAVAILABLE_WITHOUT_BROKER_CLOSE_PRICE"
    assert fake.calls[-1][:2] == (
        "GET", DEMO_CLOSE_INFO_PATH.format(order_id=202))


def test_later_broker_closed_lookup_revokes_stale_close_authority() -> None:
    fake = FakeDemoRoute([lookup(), lookup(state="closed")])
    port = EtoroDemoOrderPort(fake)
    _, earlier = port.lookup_open(request(), order_id=101)
    assert earlier is not None
    later, current = port.lookup_open(request(), order_id=101)
    assert later.status == "FILLED" and current is None
    with pytest.raises(DemoLineageRefused):
        port.submit_owned_close(close_request(), owner=earlier)
    assert all(method == "GET" for method, _, _ in fake.calls)


def test_offline_full_demo_order_cycle_404_fallback_then_close_not_flat_claim() -> None:
    """Same adapter, real contract shapes, but no broker network or account access."""
    fake = FakeDemoRoute([
        accepted(), TransportNotFound("reference lookup 404"), lookup(),
        {"orderForClose": {
            "orderID": 202, "positionID": 100001, "instrumentID": 1004,
        }},
        {"orderID": 202, "statusID": 3,
         "positions": [{"positionID": 100001, "units": 0.09}]},
    ])
    port = EtoroDemoOrderPort(fake)
    acceptance = port.submit_open(request())
    recovered = port.recover_accepted_open(
        request(), acceptance,
        wait_before_first_lookup=lambda: None,
        wait_before_order_id_fallback=lambda: None,
    )
    assert recovered.classification == "BROKER_CONFIRMED_OPEN"
    assert recovered.requests_used == 2
    owner = recovered.position
    assert owner is not None
    close_acceptance = port.submit_owned_close(close_request(), owner=owner)
    close_read = port.lookup_close(
        close_acceptance, request=close_request(), owner=owner)
    assert close_read.position_status == (
        "BROKER_REPORTS_FULL_CLOSE_PENDING_PORTFOLIO_RECONCILIATION")
    assert close_read.realised_pnl_status == "UNAVAILABLE_WITHOUT_BROKER_CLOSE_PRICE"
    assert [c[0] for c in fake.calls] == ["POST", "GET", "GET", "POST", "GET"]
    assert all("/real/" not in c[1] for c in fake.calls)


def test_cannot_rebind_accepted_reference_to_different_open_parameters() -> None:
    fake = FakeDemoRoute([accepted()])
    port = EtoroDemoOrderPort(fake)
    approval = port.submit_open(request())
    altered = DemoOpenRequest(OPEN_REFERENCE, 1004, Decimal("0.08"), Decimal("110"))
    with pytest.raises(DemoLineageRefused, match="original signed open"):
        port.lookup_open(altered, order_id=approval.order_id)
    with pytest.raises(DemoLineageRefused, match="validated acceptance"):
        port.recover_accepted_open(
            altered, approval, wait_before_first_lookup=lambda: None,
            wait_before_order_id_fallback=lambda: None,
        )
    assert len(fake.calls) == 1
