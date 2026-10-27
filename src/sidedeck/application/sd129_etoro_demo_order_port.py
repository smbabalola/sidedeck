"""SD-129 — typed eToro Demo broker port (transport-neutral, OFFLINE integration).

Reuses the verified SD-036/SD-043 v2 DEMO order contract instead of
creating a second API implementation. No credentials, environment access,
sockets, HTTP library, or authority to submit broker requests are present.

The caller supplies a transport that MUST independently enforce SD-063/064/
074F policy, write-ahead identity, request budgets, release and locks before
any call. This adapter is *not* a released broker gateway. All responses
are parsed with the existing strict lineage checks; an accepted POST never
counts as a fill. Never retry a POST after unknown outcome.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable, Protocol

from sidedeck.application.sd036_etoro_demo_desk import TransportNotFound

from sidedeck.domain.etoro_demo_orders import (
    DEMO_CLOSE_INFO_PATH, DEMO_OPEN_PATH, DEMO_ORDER_LOOKUP_PATH,
    DemoCloseRequest, DemoOpenRequest, DemoOrderOutcome, CloseOutcome,
    CloseAcceptance, OpenAcceptance, EtoroDemoOrderError,
    parse_close_acceptance, parse_close_info, parse_open_acceptance,
    parse_order_lookup, require_demo_route,
)


class DemoRoute(Protocol):
    """SD-129 has no concrete network implementation or credential access."""

    def send(self, method: str, path: str, *, reference_id: str,
             body: dict[str, Any] | None = None,
             query: dict[str, str] | None = None) -> Any: ...


class DemoLineageRefused(PermissionError):
    """Position identity could not be proven from an actual open-order lookup."""


@dataclass(frozen=True)
class ConfirmedOpen:
    """One broker-confirmed open position, never the request's assumed fill."""

    request: DemoOpenRequest
    order_id: int
    position_id: int
    units: Decimal
    remaining_units: Decimal
    avg_price: Decimal

    def __post_init__(self) -> None:
        if self.units <= 0 or self.avg_price <= 0 or \
                not Decimal(0) <= self.remaining_units <= self.units:
            raise DemoLineageRefused("confirmed position quantities are invalid")


@dataclass(frozen=True)
class RecoveredOpen:
    """Bounded GET-only recovery; acceptance alone is not an execution."""

    classification: str
    requests_used: int
    outcome: DemoOrderOutcome | None
    position: ConfirmedOpen | None


@dataclass(frozen=True)
class CloseRead:
    """Close status, NOT broker-confirmed realised P&L (price is absent)."""

    acceptance: CloseAcceptance
    outcome: CloseOutcome
    realised_pnl_status: str = "UNAVAILABLE_WITHOUT_BROKER_CLOSE_PRICE"
    position_status: str = "UNRESOLVED_REQUIRES_PORTFOLIO_RECONCILIATION"


class EtoroDemoOrderPort:
    """Only typed, allowlisted Demo calls; no order loops or trade decisions.

    Transport *must* be the separate signed, owner-released SD-107 route.
    Never wire an arbitrary transport into a production service by itself.
    """

    def __init__(self, route: DemoRoute) -> None:
        self._route = route
        # Session-local extra check, NOT a substitute for SD-063 durable lineage.
        self._verified_positions: dict[int, ConfirmedOpen] = {}
        self._open_attempts: set[str] = set()
        self._accepted_orders: dict[str, OpenAcceptance] = {}
        self._closing_positions: set[int] = set()
        self._accepted_closes: dict[str, CloseAcceptance] = {}

    def submit_open(self, request: DemoOpenRequest) -> OpenAcceptance:
        # Memory-only secondary guard; the caller MUST also use durable SD-063
        # write-ahead intent and grant counters. Reserve before potentially sent I/O.
        if request.reference_id in self._open_attempts:
            raise DemoLineageRefused("open POST already attempted; recover by GET, never resubmit")
        require_demo_route("POST", DEMO_OPEN_PATH)
        self._open_attempts.add(request.reference_id)
        payload = self._route.send(
            "POST", DEMO_OPEN_PATH, reference_id=request.reference_id,
            body=request.body(),
        )
        # A 200/echo is ACCEPTANCE, never a fill.
        acceptance = parse_open_acceptance(payload, reference_id=request.reference_id)
        self._accepted_orders[request.reference_id] = acceptance
        return acceptance

    def lookup_open(
        self, request: DemoOpenRequest, *, order_id: int | None = None,
    ) -> tuple[DemoOrderOutcome, ConfirmedOpen | None]:
        query = ({"orderId": str(order_id)} if order_id is not None else
                 {"referenceId": request.reference_id})
        require_demo_route("GET", DEMO_ORDER_LOOKUP_PATH)
        payload = self._route.send(
            "GET", DEMO_ORDER_LOOKUP_PATH,
            reference_id=f"lookup:{request.reference_id}",
            query=query,
        )
        accepted = self._accepted_orders.get(request.reference_id)
        if accepted is not None and order_id is not None and order_id != accepted.order_id:
            raise DemoLineageRefused("order lookup differs from accepted broker order")
        outcome = parse_order_lookup(
            payload, request=request,
            order_id=accepted.order_id if accepted is not None else order_id,
        )
        # Even a terminal FILLED lookup cannot modify arbitrary/baseline positions.
        # Each positionId must be from the actual order's openingData.orderId.
        if not outcome.terminal:
            return outcome, None
        if len(outcome.executions) == 0:
            return outcome, None
        if len(outcome.executions) != 1:
            raise DemoLineageRefused("multiple broker positions require operator reconciliation")
        opened = outcome.executions[0]
        if opened.state != "open" or opened.remaining_units <= 0:
            # A previously opened position may have been manually closed.
            # Do not assert ownership of a flat broker position.
            return outcome, None
        confirmed = ConfirmedOpen(
            request=request, order_id=outcome.order_id,
            position_id=opened.position_id, units=opened.units,
            remaining_units=opened.remaining_units, avg_price=opened.avg_price,
        )
        self._verified_positions[confirmed.position_id] = confirmed
        return outcome, confirmed

    def recover_accepted_open(
        self, request: DemoOpenRequest, acceptance: OpenAcceptance, *,
        wait_before_first_lookup: Callable[[], None],
        wait_before_order_id_fallback: Callable[[], None],
    ) -> RecoveredOpen:
        """Two bounded GETs, never a second POST, after an accepted order.

        First GET uses referenceId. Only a broker 404 triggers orderId fallback.
        Both wait hooks are mandatory; in production they must use an audited
        schedule (not the default 0.8s follow-up that failed the MSFT pilot).
        Missing/nonterminal/previously closed outcomes stay UNRESOLVED; a
        separate, signed /pnl recovery is outside this port's authority.
        """
        trusted = self._accepted_orders.get(request.reference_id)
        if trusted is not acceptance or trusted.order_id != acceptance.order_id:
            raise DemoLineageRefused("recovery requires this session's validated acceptance")
        if not callable(wait_before_first_lookup) or not callable(wait_before_order_id_fallback):
            raise DemoLineageRefused("both audited read-schedule hooks are required")
        wait_before_first_lookup()
        used = 1
        try:
            outcome, position = self.lookup_open(request)
        except TransportNotFound:
            wait_before_order_id_fallback()
            used += 1
            try:
                outcome, position = self.lookup_open(request, order_id=acceptance.order_id)
            except TransportNotFound:
                return RecoveredOpen("UNRESOLVED_NOT_VISIBLE", used, None, None)
        if position is not None:
            return RecoveredOpen("BROKER_CONFIRMED_OPEN", used, outcome, position)
        if outcome.terminal and not outcome.executions:
            return RecoveredOpen("TERMINAL_NO_FILL", used, outcome, None)
        # Order may still fill, or the position may already have been closed.
        # Neither is a safe instruction to submit a new open/close.
        return RecoveredOpen("UNRESOLVED", used, outcome, None)

    def submit_owned_close(
        self, request: DemoCloseRequest, *, owner: ConfirmedOpen,
    ) -> CloseAcceptance:
        if (owner.position_id in self._closing_positions or
                self._verified_positions.get(owner.position_id) is not owner or
                request.position_id != owner.position_id or
                request.instrument_id != owner.request.instrument_id or
                request.units_to_deduct is not None or
                owner.remaining_units <= 0):
            raise DemoLineageRefused(
                "close is not a full reduce-only close of a confirmed SideDeck position")
        require_demo_route("POST", request.path)
        # Reserve before I/O: an unknown close outcome must not produce a
        # second sell. Read-only reconciliation and explicit owner recovery only.
        self._closing_positions.add(owner.position_id)
        payload = self._route.send(
            "POST", request.path, reference_id=request.reference_id,
            body=request.body(),
        )
        acceptance = parse_close_acceptance(payload, request=request)
        self._accepted_closes[request.reference_id] = acceptance
        return acceptance

    def lookup_close(
        self, acceptance: CloseAcceptance, *, request: DemoCloseRequest,
        owner: ConfirmedOpen,
    ) -> CloseRead:
        if (self._verified_positions.get(owner.position_id) is not owner or
                self._accepted_closes.get(request.reference_id) is not acceptance or
                request.position_id != owner.position_id or
                acceptance.position_id != owner.position_id or
                request.instrument_id != owner.request.instrument_id):
            raise DemoLineageRefused("close lookup is for a different position")
        path = DEMO_CLOSE_INFO_PATH.format(order_id=acceptance.order_id)
        require_demo_route("GET", path)
        payload = self._route.send(
            "GET", path, reference_id=f"close-lookup:{request.reference_id}",
        )
        outcome = parse_close_info(payload, acceptance=acceptance)
        if outcome.closed_units > owner.remaining_units:
            raise EtoroDemoOrderError("close reported more units than SideDeck owned")
        if outcome.status == "FILLED" and outcome.closed_units == owner.remaining_units:
            # Broker close-info has no execution price and does not prove the
            # /pnl snapshot is flat; a separately authorized read is required.
            state = "BROKER_REPORTS_FULL_CLOSE_PENDING_PORTFOLIO_RECONCILIATION"
        elif outcome.terminal and outcome.closed_units == 0:
            state = "BROKER_REPORTS_NO_CLOSE"
        else:
            state = "UNRESOLVED_PARTIAL_OR_PENDING"
        return CloseRead(acceptance, outcome, position_status=state)
