"""SD-107 policy-bound offline gateway scaffold.

This module intentionally has no network transport.  The only executable gateway in this
branch is ``OfflineDemoGateway`` and it accepts only the deterministic local simulator.  The
eToro Demo deployment route remains ``NOT_RELEASED`` until the separate broker lifecycle,
off-machine anchoring, independent review and owner release are complete.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable, Protocol

from sidedeck.application.sd063_autonomous_demo_policy import (
    AutonomousDemoPolicy, EntryProposal, ExitProposal, MAX_EXIT_FILL_DEVIATION,
    PolicyRefused, _UNKNOWN_OUTCOMES,
    check_grant_binding,
)
from sidedeck.application.sd068_track_scheduler import NEW_YORK
from sidedeck.application.sd064_unlock_grant import (
    GrantRefused, UnlockAuthority,
)
from sidedeck.application.sd074_trusted_inputs import (
    AuthenticatedRuntime, BrokerQuote, Envelope, SourceSigner,
)
from sidedeck.application.sd108_broker_adapters import (
    EtoroDemoReconciliationAdapter,
)
from sidedeck.domain.etoro_demo_orders import (
    CloseAcceptance, DemoCloseRequest, DemoOpenRequest, parse_close_acceptance,
)
from sidedeck.application.sd072_track_risk_limits import (
    TrackLimits, TrackRiskState, evaluate_track_risk,
)

BROKER_ROUTES = {"ETORO_DEMO": "NOT_RELEASED"}
SUBMISSION = "SIMULATED_LOCAL"


class GatewayRefused(PermissionError):
    """The policy or send-time checks refused the proposed simulation."""


@dataclass(frozen=True)
class SimulatedOrder:
    order_id: int
    request: DemoOpenRequest
    payload: dict[str, object]


class OpenSimulator(Protocol):
    """Narrow interface implemented only by the local deterministic simulator."""

    def open(self, request: DemoOpenRequest) -> dict[str, object]: ...

    def lookup(self, order_id: int) -> dict[str, object]: ...

    def close(self, request: DemoCloseRequest) -> tuple[dict[str, object],
                                                         dict[str, object], Decimal]: ...


class OfflineDemoSimulator:
    """Deterministic local fills; never performs I/O and never represents broker evidence."""

    def __init__(self, *, fill_price: Decimal, close_price: Decimal | None = None,
                 malformed_lookup: bool = False) -> None:
        if not fill_price.is_finite() or fill_price <= 0:
            raise ValueError("simulator fill price must be positive and finite")
        self._fill_price = fill_price
        self._close_price = close_price if close_price is not None else fill_price
        if not self._close_price.is_finite() or self._close_price <= 0:
            raise ValueError("simulator close price must be positive and finite")
        self._malformed_lookup = malformed_lookup
        self._orders: dict[int, SimulatedOrder] = {}
        self._positions: dict[int, tuple[int, Decimal, bool]] = {}
        self._next_order_id = 1

    @property
    def submitted_orders(self) -> int:
        return len(self._orders)

    def open(self, request: DemoOpenRequest) -> dict[str, object]:
        if request.max_notional_usd <= 0 or request.limit_rate < self._fill_price:
            raise GatewayRefused("simulated IOC is not marketable within its limit")
        order_id = self._next_order_id
        self._next_order_id += 1
        acceptance: dict[str, object] = {"orderId": order_id,
                                         "referenceId": request.reference_id}
        self._orders[order_id] = SimulatedOrder(order_id, request, acceptance)
        return acceptance

    def lookup(self, order_id: int) -> dict[str, object]:
        order = self._orders.get(order_id)
        if order is None:
            raise GatewayRefused("simulated order does not exist")
        if self._malformed_lookup:
            return {"orderId": order_id, "status": "unexpected"}
        request = order.request
        position_id = order_id + 100_000
        self._positions.setdefault(position_id, (request.instrument_id, request.units, False))
        return {
            "orderId": order_id, "action": "open", "transaction": "buy",
            "status": {"id": 3, "errorCode": 0},
            "asset": {"instrumentId": request.instrument_id, "leverage": 1,
                      "side": "long"},
            "positionExecutions": [{
                "positionId": position_id, "state": "open",
                "remainingUnits": float(request.units),
                "openingData": {"orderId": order_id, "units": float(request.units),
                                "avgPrice": float(self._fill_price), "fees": 0.0},
            }],
        }

    def close(self, request: DemoCloseRequest) -> tuple[dict[str, object],
                                                          dict[str, object], Decimal]:
        position = self._positions.get(request.position_id)
        if position is None or position[0] != request.instrument_id or position[2]:
            raise GatewayRefused("simulator position is missing, closed or mismatched")
        remaining = position[1]
        units = request.units_to_deduct if request.units_to_deduct is not None else remaining
        if units != remaining:
            raise GatewayRefused("simulator supports only full reduce-only closes")
        self._positions[request.position_id] = (position[0], Decimal("0"), True)
        order_id = self._next_order_id
        self._next_order_id += 1
        acceptance: dict[str, object] = {"orderForClose": {
            "positionID": request.position_id, "instrumentID": request.instrument_id,
            "orderID": order_id}}
        close_info: dict[str, object] = {"orderID": order_id, "statusID": 3,
                                        "positions": [{"positionID": request.position_id,
                                                       "units": float(units)}]}
        return acceptance, close_info, self._close_price


class OfflineDemoGateway:
    """Require SD-064 grants, SD-063 proposals and SD-074 seals before local simulation.

    This class is deliberately unable to select an HTTP client.  Deployable broker transport
    must be a separately reviewed implementation; changing ``BROKER_ROUTES`` here cannot
    unlock the SD-103 production route.
    """

    def __init__(self, *, policy: AutonomousDemoPolicy,
                 runtime: AuthenticatedRuntime, authority: UnlockAuthority,
                 grant_document: dict[str, object], grant_signature: str,
                 simulator: OfflineDemoSimulator, reconciliation_signer: SourceSigner,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        if type(simulator) is not OfflineDemoSimulator:
            raise GatewayRefused("only the offline simulator is accepted by this gateway")
        if runtime.ledger.policy_digest != policy.digest():
            raise GatewayRefused("runtime ledger is bound to a different policy")
        self._policy, self._runtime, self._authority = policy, runtime, authority
        self._document, self._signature = grant_document, grant_signature
        self._simulator, self._clock = simulator, clock
        self._adapter = EtoroDemoReconciliationAdapter(reconciliation_signer)

    def _authorize(self, *, write: bool, reference_id: str) -> None:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise GatewayRefused("gateway clock must be timezone-aware")
        try:
            grant = self._authority.authorize_request(
                document=self._document, signature=self._signature,
                subject_digest=self._policy.digest(), write=write,
                reference_id=reference_id, now=now,
            )
            check_grant_binding(self._policy, grant, now.astimezone(timezone.utc))
        except (GrantRefused, PolicyRefused) as exc:
            raise GatewayRefused("signed grant refused") from exc

    def _validate_entry_at_send(self, proposal: EntryProposal, now: datetime,
                                quotes: dict[str, BrokerQuote]) -> None:
        if proposal.submission != "OFFLINE_PROPOSAL_NOT_SUBMITTED":
            raise GatewayRefused("proposal submission state is not eligible")
        if proposal.policy_digest != self._policy.digest():
            raise GatewayRefused("proposal belongs to a different policy")
        if not self._policy.active(now):
            raise GatewayRefused("policy is outside its signed window")
        if (now - proposal.proposed_at).total_seconds() > self._policy.max_quote_age_seconds:
            raise GatewayRefused("proposal quote freshness expired before send")
        if self._runtime.ledger.kill_switch_engaged():
            raise GatewayRefused("policy kill-switch is engaged")
        state = self._runtime.ledger.state()
        entry = state.entries.get(proposal.reference_id)
        if entry is None or entry.outcome is not None:
            raise GatewayRefused("proposal is absent, resolved or already submitted")
        if (entry.track, entry.canonical_id, entry.instrument, entry.units, entry.limit) != (
                proposal.track, proposal.canonical_id, proposal.etoro_instrument_id,
                proposal.units, proposal.limit_price):
            raise GatewayRefused("proposal does not match the durable policy ledger")
        current = quotes.get(proposal.canonical_id)
        if current is None or current.ask > proposal.limit_price:
            raise GatewayRefused("fresh sealed ask is absent or above the proposal limit")
        budget = self._policy.budget(proposal.track)
        if budget is None or entry.units * entry.limit > budget.max_position_notional:
            raise GatewayRefused("per-position notional cap exceeded")
        day = now.astimezone(NEW_YORK).date()
        order_count = self._runtime.ledger.count_events(
            ("ENTRY_PROPOSED", "EXIT_PROPOSED"), proposal.track, day)
        if order_count > budget.max_orders_per_day:
            raise GatewayRefused("daily order cap exceeded at send time")
        exposure = sum((p.units * p.avg_price
                        for p in self._runtime.ledger.open_positions()), Decimal("0"))
        exposure += sum((p.units * p.limit for p in state.entries.values()
                         if p.outcome is None or p.outcome in _UNKNOWN_OUTCOMES), Decimal("0"))
        total_capital = sum((b.virtual_capital for b in self._policy.tracks), Decimal("0"))
        if exposure > total_capital or exposure > Decimal("1000"):
            raise GatewayRefused("aggregate exposure cap exceeded at send time")
        marks = {canonical: quote.bid for canonical, quote in quotes.items()}
        runtime = self._runtime.runtime
        equity = runtime._equity(state, proposal.track, budget.virtual_capital, marks)
        if equity is None:
            raise GatewayRefused("fresh marks for every open position are required at send time")
        prior_peak = max([budget.virtual_capital,
                          *(value for _, value in state.marks.get(proposal.track, []))])
        start = next((value for mark_day, value in state.marks.get(proposal.track, [])
                      if mark_day == day.isoformat()), None)
        if start is None or equity <= budget.virtual_capital * (1 - budget.max_loss_pct):
            raise GatewayRefused("daily or cumulative loss gate cannot be verified at send time")
        risk = evaluate_track_risk(
            TrackRiskState(proposal.track, equity, max(prior_peak, equity), start, order_count),
            TrackLimits(proposal.track, budget.max_drawdown_pct, budget.max_daily_loss_pct,
                        budget.max_orders_per_day),
        )
        if not risk.entries_allowed:
            raise GatewayRefused("send-time risk gate refused the entry")

    def submit_entry(self, proposal: EntryProposal, *, quote: Envelope,
                     marks: tuple[Envelope, ...] = ()) -> Envelope:
        """Simulate one guarded open and reconcile it through the sealed SD-074 path."""
        now = self._clock()
        try:
            verified_quotes = [self._runtime.verified_quote(envelope)
                               for envelope in (quote, *marks)]
        except Exception as exc:
            raise GatewayRefused("send-time quote verification failed") from exc
        if len({item.canonical_id for item in verified_quotes}) != len(verified_quotes):
            raise GatewayRefused("duplicate send-time quote for an instrument")
        self._validate_entry_at_send(
            proposal, now, {item.canonical_id: item for item in verified_quotes})
        request_id = str(uuid.UUID(hex=proposal.reference_id))
        request = DemoOpenRequest(request_id, proposal.etoro_instrument_id, proposal.units,
                                  proposal.limit_price)
        self._authorize(write=True, reference_id=proposal.reference_id)
        try:
            accepted = self._simulator.open(request)
            try:
                acceptance = self._adapter.parse_open_acceptance(accepted, request=request)
            except Exception as exc:
                self._runtime.ledger.trip_kill_switch("SIMULATED_OPEN_AMBIGUOUS", now)
                raise GatewayRefused("simulated open acceptance is malformed") from exc
            self._authorize(write=False, reference_id=f"lookup:{proposal.reference_id}")
            raw = self._simulator.lookup(acceptance.order_id)
            envelope = self._adapter.seal_open_lookup_or_unresolved(
                raw, request=request, observed_at=self._clock(),
                accepted_order_id=acceptance.order_id)
            self._runtime.resolve(envelope)
            return envelope
        except Exception:
            # No replay/retry: any uncertain post-send result halts this policy.
            if not self._runtime.ledger.kill_switch_engaged():
                self._runtime.ledger.trip_kill_switch("SIMULATED_OUTCOME_UNRESOLVED", now)
            raise

    def submit_exit(self, proposal: ExitProposal, *, quote: Envelope) -> Envelope:
        """Simulate a lineage-verified full close; protective authority is not wired here."""
        now = self._clock()
        try:
            fresh = self._runtime.verified_quote(quote)
        except Exception as exc:
            raise GatewayRefused("exit quote verification failed") from exc
        if proposal.authority != "policy":
            raise GatewayRefused("separate protective-exit grant is required")
        if proposal.submission != "OFFLINE_PROPOSAL_NOT_SUBMITTED" \
                or proposal.policy_digest != self._policy.digest() \
                or not self._policy.active(now):
            raise GatewayRefused("exit proposal is outside its policy scope")
        if fresh.canonical_id != proposal.canonical_id or fresh.bid <= 0:
            raise GatewayRefused("fresh sealed bid does not match the exit instrument")
        state = self._runtime.ledger.state()
        exit_row = state.exits.get(proposal.reference_id)
        entry = state.entries.get(proposal.entry_reference)
        if exit_row is None or exit_row.outcome is not None or entry is None:
            raise GatewayRefused("exit proposal is absent or already resolved")
        positions = {p.entry_reference: p for p in self._runtime.ledger.open_positions()}
        position = positions.get(proposal.entry_reference)
        if position is None or not position.broker_position_id or \
                str(position.broker_position_id) != str(proposal.broker_position_id):
            raise GatewayRefused("exit lacks verified SideDeck position lineage")
        if not position.broker_position_id.isdecimal():
            raise GatewayRefused("broker position id is not a numeric eToro position id")
        if (proposal.policy_digest != self._policy.digest()
                or (exit_row.entry, exit_row.units) !=
                (proposal.entry_reference, proposal.units)
                or (entry.track, entry.canonical_id, entry.instrument) !=
                (proposal.track, proposal.canonical_id, proposal.etoro_instrument_id)):
            raise GatewayRefused("exit proposal does not match the durable ledger")
        if abs(fresh.bid - exit_row.bid) > exit_row.bid * MAX_EXIT_FILL_DEVIATION:
            raise GatewayRefused("fresh bid differs materially from the planned close")
        if proposal.units != position.units or proposal.etoro_instrument_id in \
                self._policy.protected_instrument_ids:
            raise GatewayRefused("only a full reduce-only close of an owned position is allowed")
        if (now - proposal.proposed_at).total_seconds() > self._policy.max_quote_age_seconds:
            raise GatewayRefused("exit quote freshness expired before send")
        if entry.instrument != proposal.etoro_instrument_id \
                or entry.canonical_id != proposal.canonical_id:
            raise GatewayRefused("exit instrument does not match the position lineage")
        budget = self._policy.budget(proposal.track)
        if budget is None:
            raise GatewayRefused("exit track is outside the policy")
        day = now.astimezone(NEW_YORK).date()
        order_count = self._runtime.ledger.count_events(
            ("ENTRY_PROPOSED", "EXIT_PROPOSED"), proposal.track, day)
        if order_count > budget.max_orders_per_day:
            raise GatewayRefused("daily order cap exceeded at close send time")

        request = DemoCloseRequest(str(uuid.UUID(hex=proposal.reference_id)),
                                    int(position.broker_position_id),
                                    proposal.etoro_instrument_id, proposal.units)
        self._authorize(write=True, reference_id=proposal.reference_id)
        try:
            accepted_payload, close_payload, fill_price = self._simulator.close(request)
            try:
                acceptance: CloseAcceptance = parse_close_acceptance(
                    accepted_payload, request=request)
            except Exception as exc:
                self._runtime.ledger.trip_kill_switch("SIMULATED_CLOSE_AMBIGUOUS", now)
                raise GatewayRefused("simulated close acceptance is malformed") from exc
            self._authorize(write=False, reference_id=f"close-lookup:{proposal.reference_id}")
            envelope = self._adapter.seal_simulated_close(
                close_payload, request=request, acceptance=acceptance,
                observed_at=self._clock(), fill_price=fill_price)
            self._runtime.resolve(envelope)
            return envelope
        except Exception:
            if not self._runtime.ledger.kill_switch_engaged():
                self._runtime.ledger.trip_kill_switch("SIMULATED_CLOSE_UNRESOLVED", now)
            raise

