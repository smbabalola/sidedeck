"""Disposable, in-memory paper-release operator rehearsal.

This is a state-machine test harness, not a broker adapter.  It has no HTTP,
credentials, account state or order submission capability.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any


class RehearsalError(ValueError):
    pass


@dataclass(frozen=True)
class Approval:
    approval_id: str
    approved_by: str
    signature: str
    scope: str


@dataclass(frozen=True)
class SimulatedOrder:
    intent_id: str
    client_order_id: str
    portfolio_id: str
    instrument_id: str
    quantity: Decimal
    state: str = "PROPOSED"
    approved: bool = False
    filled_quantity: Decimal = Decimal("0")
    exit_quantity: Decimal = Decimal("0")


class DryRunDesk:
    """Deterministic local rehearsal desk with append-only event history."""

    def __init__(self) -> None:
        self._orders: dict[str, SimulatedOrder] = {}
        self._events: list[dict[str, Any]] = []
        self._halted = False

    @property
    def events(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._events)

    def propose(self, order: SimulatedOrder) -> SimulatedOrder:
        if order.quantity <= 0 or not order.quantity.is_finite():
            raise RehearsalError("positive finite quantity is required")
        if order.client_order_id in self._orders:
            existing = self._orders[order.client_order_id]
            if existing != order:
                raise RehearsalError("client order idempotency conflict")
            return existing
        self._orders[order.client_order_id] = order
        self._events.append({"type": "INTENT_PROPOSED", "client_order_id": order.client_order_id})
        return order

    def approve(self, client_order_id: str, approval: Approval) -> SimulatedOrder:
        order = self._get(client_order_id)
        if order.state != "PROPOSED":
            raise RehearsalError("only proposed intent can be approved")
        if not approval.approval_id.strip() or not approval.approved_by.strip() or not approval.signature.strip():
            raise RehearsalError("complete human approval record is required")
        if approval.approved_by.lower() in {"system", "strategy", "sidedeck", "auto"}:
            raise RehearsalError("approval must be external to the strategy system")
        updated = replace(order, approved=True, state="APPROVED")
        self._orders[client_order_id] = updated
        self._events.append({"type": "HUMAN_APPROVED", "client_order_id": client_order_id, "approval_id": approval.approval_id})
        return updated

    def submit_simulated(self, client_order_id: str) -> SimulatedOrder:
        if self._halted:
            raise RehearsalError("emergency stop is active")
        order = self._get(client_order_id)
        if order.state == "SUBMITTED_SIMULATED":
            return order
        if order.state != "APPROVED" or not order.approved:
            raise RehearsalError("independent human approval is required")
        updated = replace(order, state="SUBMITTED_SIMULATED")
        self._orders[client_order_id] = updated
        self._events.append({"type": "SUBMISSION_SIMULATED", "client_order_id": client_order_id})
        return updated

    def acknowledge(self, client_order_id: str) -> SimulatedOrder:
        order = self._get(client_order_id)
        if order.state != "SUBMITTED_SIMULATED":
            raise RehearsalError("simulated submission acknowledgement is out of order")
        updated = replace(order, state="ACKED")
        self._orders[client_order_id] = updated
        self._events.append({"type": "ACK_RECEIVED", "client_order_id": client_order_id})
        return updated

    def fill(self, client_order_id: str, quantity: Decimal) -> SimulatedOrder:
        order = self._get(client_order_id)
        if order.state not in {"ACKED", "PARTIALLY_FILLED"} or quantity <= 0:
            raise RehearsalError("invalid simulated fill")
        filled = order.filled_quantity + quantity
        if filled > order.quantity:
            raise RehearsalError("fill exceeds intent quantity")
        state = "FILLED" if filled == order.quantity else "PARTIALLY_FILLED"
        updated = replace(order, state=state, filled_quantity=filled)
        self._orders[client_order_id] = updated
        self._events.append({"type": "FILL_SIMULATED", "client_order_id": client_order_id, "quantity": str(quantity)})
        return updated

    def exit(self, client_order_id: str, quantity: Decimal) -> SimulatedOrder:
        order = self._get(client_order_id)
        if order.state != "FILLED" or quantity <= 0 or order.exit_quantity + quantity > order.filled_quantity:
            raise RehearsalError("invalid simulated exit")
        exited = order.exit_quantity + quantity
        updated = replace(order, state="EXITED" if exited == order.filled_quantity else "FILLED", exit_quantity=exited)
        self._orders[client_order_id] = updated
        self._events.append({"type": "EXIT_SIMULATED", "client_order_id": client_order_id, "quantity": str(quantity)})
        return updated

    def emergency_stop(self) -> None:
        self._halted = True
        self._events.append({"type": "EMERGENCY_STOP"})

    def recover(self) -> None:
        self._halted = False
        self._events.append({"type": "RECOVERY"})

    def replay(self) -> dict[str, SimulatedOrder]:
        """Return a copy of current state; no external side effects occur."""
        return dict(self._orders)

    def rollback_last_fill(self, client_order_id: str) -> SimulatedOrder:
        order = self._get(client_order_id)
        if order.filled_quantity <= 0:
            raise RehearsalError("no fill to roll back")
        updated = replace(order, state="ACKED", filled_quantity=Decimal("0"))
        self._orders[client_order_id] = updated
        self._events.append({"type": "ROLLBACK_FILL", "client_order_id": client_order_id})
        return updated

    def _get(self, client_order_id: str) -> SimulatedOrder:
        try:
            return self._orders[client_order_id]
        except KeyError as exc:
            raise RehearsalError("unknown client order") from exc


def rehearsal_report() -> dict[str, Any]:
    desk = DryRunDesk()
    order = SimulatedOrder("intent-1", "client-1", "tradingagents", "US:SPY", Decimal("2"))
    desk.propose(order)
    desk.approve("client-1", Approval("approval-1", "owner-reviewer", "sig:offline", "US:SPY"))
    desk.submit_simulated("client-1")
    desk.acknowledge("client-1")
    desk.fill("client-1", Decimal("1"))
    desk.fill("client-1", Decimal("1"))
    desk.exit("client-1", Decimal("2"))
    return {"status": "REHEARSED", "final_state": desk.replay()["client-1"].state,
            "event_count": len(desk.events), "broker_execution": "DISABLED"}
