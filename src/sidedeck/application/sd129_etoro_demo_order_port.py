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

from sidedeck.application.sd036_etoro_demo_desk import EtoroDemoLineage, TransportNotFound

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

    def __init__(self, route: DemoRoute, *, lineage: EtoroDemoLineage | None = None) -> None:
        self._route = route
        # Opt-in reuse of SD-036's supervised durable SQLite lineage. The route itself
        # must still independently enforce owner-signed grants and the network lock.
        self._lineage = lineage
        # Session-local extra check, NOT a substitute for SD-063 durable lineage.
        self._verified_positions: dict[int, ConfirmedOpen] = {}
        self._open_attempts: set[str] = set()
        self._accepted_orders: dict[str, OpenAcceptance] = {}
        self._accepted_requests: dict[str, DemoOpenRequest] = {}
        self._closing_positions: set[int] = set()
        self._accepted_closes: dict[str, CloseAcceptance] = {}

    def submit_open(self, request: DemoOpenRequest, *,
                    intent_id: str | None = None,
                    book_id: str | None = None) -> OpenAcceptance:
        # A bound durable lineage reserves the x-request-id before attempting a
        # potentially delivered POST. A prior reservation always refuses replay,
        # even if process death occurred before the acceptance was recorded.
        if request.reference_id in self._open_attempts:
            raise DemoLineageRefused("open POST already attempted; recover by GET, never resubmit")
        require_demo_route("POST", DEMO_OPEN_PATH)
        if self._lineage is not None:
            if not intent_id or not book_id:
                raise DemoLineageRefused("durable open requires intent and strategy book identity")
            self._lineage.record_pending(
                reference_id=request.reference_id, kind="OPEN", intent_id=intent_id,
                book_id=book_id, instrument_id=request.instrument_id,
                units=request.units, limit_rate=request.limit_rate, position_id=None,
            )
        self._open_attempts.add(request.reference_id)
        payload = self._route.send(
            "POST", DEMO_OPEN_PATH, reference_id=request.reference_id,
            body=request.body(),
        )
        # A 200/echo is ACCEPTANCE, never a fill.
        acceptance = parse_open_acceptance(payload, reference_id=request.reference_id)
        if self._lineage is not None:
            self._lineage.set_state(request.reference_id, "ACCEPTED",
                                    order_id=acceptance.order_id)
        self._accepted_orders[request.reference_id] = acceptance
        self._accepted_requests[request.reference_id] = request
        return acceptance

    def _durable_open(self, request: DemoOpenRequest) -> Any:
        if self._lineage is None:
            return None
        row = self._lineage.order(request.reference_id)
        if (row["kind"] != "OPEN" or row["instrument_id"] != request.instrument_id
                or row["units"] != str(request.units)
                or row["limit_rate"] != str(request.limit_rate)):
            raise DemoLineageRefused("durable open identity differs from the original intent")
        return row

    def lookup_open(
        self, request: DemoOpenRequest, *, order_id: int | None = None,
    ) -> tuple[DemoOrderOutcome, ConfirmedOpen | None]:
        if (request.reference_id in self._accepted_requests and
                self._accepted_requests[request.reference_id] != request):
            raise DemoLineageRefused("lookup request differs from original signed open")
        row = self._durable_open(request)
        durable_order_id = row["order_id"] if row is not None else None
        if durable_order_id is not None and order_id is not None and order_id != durable_order_id:
            raise DemoLineageRefused("order lookup differs from durable accepted order")
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
            order_id=(accepted.order_id if accepted is not None else
                      durable_order_id if durable_order_id is not None else order_id),
        )
        if row is not None and durable_order_id is None:
            assert self._lineage is not None
            # A lost POST acknowledgement can be recovered from a genuine,
            # independently authorised read; never issue another open POST.
            self._lineage.set_state(request.reference_id, "ACCEPTED",
                                    order_id=outcome.order_id)
        # Any later authoritative lookup replaces earlier session-local evidence.
        # A manually closed/vanished position must not retain close authority
        # just because an old ConfirmedOpen object still exists in memory.
        for position_id, prior in tuple(self._verified_positions.items()):
            if prior.request.reference_id == request.reference_id:
                del self._verified_positions[position_id]
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
        if row is not None:
            assert self._lineage is not None
            self._lineage.register_position(
                reference_id=request.reference_id, order_id=outcome.order_id,
                book_id=row["book_id"], instrument_id=request.instrument_id,
                position_id=confirmed.position_id, units=confirmed.units,
                remaining=confirmed.remaining_units,
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
        if self._lineage is not None:
            row = self._durable_open(request)
            if (row["order_id"] is None or row["state"] != "ACCEPTED"
                    or row["order_id"] != acceptance.order_id
                    or acceptance.reference_id != request.reference_id):
                raise DemoLineageRefused("recovery requires durable validated acceptance")
        elif (trusted is not acceptance or trusted.order_id != acceptance.order_id or
              self._accepted_requests.get(request.reference_id) != request):
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
        intent_id: str | None = None, book_id: str | None = None,
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
        if self._lineage is not None:
            if not intent_id or not book_id:
                raise DemoLineageRefused("durable close requires intent and strategy book identity")
            owned = self._lineage.owned(owner.position_id)
            if (owned is None or owned["reference_id"] != owner.request.reference_id
                    or owned["order_id"] != owner.order_id
                    or owned["instrument_id"] != request.instrument_id
                    or owned["book_id"] != book_id
                    or owned["remaining_units"] != str(owner.remaining_units)
                    or owned["state"] != "OPEN"):
                raise DemoLineageRefused("durable close lacks exact SideDeck open lineage")
            # SQLite's unique unresolved-close index fences competing workers even
            # if both had separately verified the same broker position by GET.
            self._lineage.record_pending(
                reference_id=request.reference_id, kind="CLOSE", intent_id=intent_id,
                book_id=book_id, instrument_id=request.instrument_id,
                units=owner.remaining_units, limit_rate=None,
                position_id=owner.position_id,
            )
        # Reserve before I/O: an unknown close outcome must not produce a
        # second sell. Read-only reconciliation and explicit owner recovery only.
        self._closing_positions.add(owner.position_id)
        payload = self._route.send(
            "POST", request.path, reference_id=request.reference_id,
            body=request.body(),
        )
        acceptance = parse_close_acceptance(payload, request=request)
        if self._lineage is not None:
            self._lineage.set_state(request.reference_id, "ACCEPTED",
                                    order_id=acceptance.order_id)
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

    def recover_close_info(
        self, acceptance: CloseAcceptance, *, request: DemoCloseRequest,
    ) -> CloseRead:
        """GET-only restart recovery for a durably accepted close; never proves flat/P&L.

        Requires existing protected-baseline-aware SD-036 lineage and a transport
        that independently authorizes/counters the broker GET. A lost close
        acceptance (no stored orderId) must use separately authorized /pnl
        reconciliation, never a second POST.
        """
        if self._lineage is None:
            raise DemoLineageRefused("durable close recovery requires persisted lineage")
        row = self._lineage.order(request.reference_id)
        owned = self._lineage.owned(request.position_id)
        if (row["kind"] != "CLOSE" or row["state"] != "ACCEPTED"
                or row["position_id"] != request.position_id
                or row["instrument_id"] != request.instrument_id
                or row["order_id"] != acceptance.order_id
                or acceptance.position_id != request.position_id
                or request.units_to_deduct is not None
                or owned is None or owned["book_id"] != row["book_id"]
                or owned["instrument_id"] != request.instrument_id
                or owned["position_id"] != request.position_id):
            raise DemoLineageRefused("durable close acceptance or ownership is inconsistent")
        path = DEMO_CLOSE_INFO_PATH.format(order_id=acceptance.order_id)
        require_demo_route("GET", path)
        payload = self._route.send(
            "GET", path, reference_id=f"close-recovery:{request.reference_id}",
        )
        outcome = parse_close_info(payload, acceptance=acceptance)
        if outcome.closed_units > Decimal(row["units"]):
            raise EtoroDemoOrderError("close reported more units than the reserved full close")
        if outcome.status == "FILLED" and outcome.closed_units == Decimal(row["units"]):
            state = "BROKER_REPORTS_FULL_CLOSE_PENDING_PORTFOLIO_RECONCILIATION"
        elif outcome.terminal and outcome.closed_units == 0:
            state = "BROKER_REPORTS_NO_CLOSE"
        else:
            state = "UNRESOLVED_PARTIAL_OR_PENDING"
        return CloseRead(acceptance, outcome, position_status=state)
