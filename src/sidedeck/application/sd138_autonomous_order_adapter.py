"""SD-138: compose SD-063/064/074/145 with the durable SD-129 port.

This implementation deliberately accepts only the repository's deterministic fake route.
It is integration code for offline verification, not a live broker gateway or release.
"""
from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from decimal import Decimal

from sidedeck.application.sd063_autonomous_demo_policy import (
    EntryProposal, ExitProposal, _UNKNOWN_OUTCOMES,
)
from sidedeck.application.sd107_demo_gateway import (
    OfflineDemoGateway,
)
from sidedeck.application.sd129_etoro_demo_order_port import (
    CloseRead, ConfirmedOpen, EtoroDemoOrderPort,
)
from sidedeck.domain.etoro_demo_orders import CloseOutcome, DemoOpenRequest
from sidedeck.application.sd074_trusted_inputs import Envelope
from sidedeck.domain.etoro_demo import parse_demo_portfolio


@dataclass(frozen=True)
class AutonomousOpenResult:
    classification: str
    acceptance_order_id: int | None
    position: ConfirmedOpen | None
    evidence: Envelope | None


@dataclass(frozen=True)
class AutonomousCloseResult:
    """Offline close plus whole-account observation; economics stay simulation-only."""
    close_read: CloseRead
    snapshot_sha256: str
    baseline_position_ids: tuple[int, ...]

    @property
    def classification(self) -> str:
        return "SIMULATED_ROUND_TRIP_CLOSED"

    @property
    def outcome(self) -> CloseOutcome:
        return self.close_read.outcome

    @property
    def realised_pnl_status(self) -> str:
        return "SIMULATED_ONLY_NOT_BROKER_PNL"

    @property
    def position_status(self) -> str:
        return "FLAT_CONFIRMED_BY_SIMULATED_CLOSE_AND_FINAL_PNL"


class SD138Refused(PermissionError):
    """Policy, grant, evidence, lineage, or audit prerequisites failed closed."""


class AutonomousEtoroDemoOrderAdapter:
    """Policy-gated SD-129 composition for deterministic fake eToro Demo transport only.

    The SD-107 gateway remains the source of policy/risk decisions, signed grants,
    trusted-input verification, policy anchoring and audit-journal writes. This adapter
    adds durable SD-036 order lineage around those same gates; it creates no new ledger
    or authorization scheme.
    """

    def __init__(self, *, policy_gateway: OfflineDemoGateway,
                 order_port: EtoroDemoOrderPort) -> None:
        if type(policy_gateway) is not OfflineDemoGateway:
            raise SD138Refused("the existing SD-107 policy gateway is required")
        if type(order_port) is not EtoroDemoOrderPort:
            raise SD138Refused("the typed SD-129 order port is required")
        if not order_port.has_durable_lineage:
            raise SD138Refused("durable SD-036 order lineage is required")
        if not order_port.is_offline_fake_route:
            raise SD138Refused("only the deterministic offline fake broker route is allowed")
        if policy_gateway._audit_journal is None:
            raise SD138Refused("anchored SD-145 audit journal is required")
        self._gate = policy_gateway
        self._port = order_port
        self._owners: dict[str, ConfirmedOpen] = {}

    def _book_for(self, proposal: EntryProposal) -> str:
        try:
            return self._gate._policy.book_for_strategies(
                proposal.strategies, track=proposal.track)
        except Exception as exc:
            raise SD138Refused("proposal has no single signed SideDeck book") from exc

    def _open_request(self, proposal: EntryProposal) -> DemoOpenRequest:
        if not isinstance(proposal, EntryProposal):
            raise SD138Refused("an SD-063 entry proposal is required")
        if (proposal.policy_digest != self._gate._policy.digest()
                or proposal.direction != "BUY" or proposal.order_type != "limitIOC"
                or proposal.leverage != 1):
            raise SD138Refused("open proposal differs from the signed policy scope")
        try:
            reference = str(uuid.UUID(hex=proposal.reference_id))
        except (ValueError, AttributeError):
            raise SD138Refused("proposal reference is not a canonical durable ID") from None
        return DemoOpenRequest(reference, proposal.etoro_instrument_id,
                               proposal.units, proposal.limit_price)

    def _record_reconciliation(self, reference_id: str, action: str,
                               envelope: Envelope) -> None:
        self._gate._audit(
            "RECONCILIATION", reference_id,
            payload={"action": action,
                     "outcome": str(envelope.payload.get("outcome")),
                     "evidence_sha256": hashlib.sha256(envelope.canonical()).hexdigest()},
        )
        self._gate._publish_before_send(self._gate._clock())

    def submit_entry(self, proposal: EntryProposal, *, quote: Envelope,
                     marks: tuple[Envelope, ...] = ()) -> AutonomousOpenResult:
        request = self._open_request(proposal)
        book_id = self._book_for(proposal)
        now = self._gate._clock()
        try:
            verified = [self._gate._runtime.verified_quote(item)
                        for item in (quote, *marks)]
        except Exception as exc:
            raise SD138Refused("SD-074 send-time quote verification failed") from exc
        if len({item.canonical_id for item in verified}) != len(verified):
            raise SD138Refused("duplicate send-time quote evidence")
        self._gate._validate_entry_at_send(
            proposal, now, {item.canonical_id: item for item in verified})
        self._gate._audit(
            "ORDER_RESERVATION", proposal.reference_id,
            payload={"action": "OPEN", "policy_digest": proposal.policy_digest,
                     "book_id": book_id, "units": str(proposal.units),
                     "instrument_id": proposal.etoro_instrument_id},
        )
        self._gate._authorize(write=True, reference_id=request.reference_id)
        try:
            self._gate._audit("SEND", request.reference_id,
                              payload={"action": "OPEN", "policy_digest": proposal.policy_digest,
                                       "book_id": book_id,
                                       "intent_reference": proposal.reference_id})
            acceptance = self._port.submit_open(
                request, intent_id=proposal.reference_id, book_id=book_id)
            lookup_ref = f"lookup:{request.reference_id}"
            self._gate._authorize(write=False, reference_id=lookup_ref)
            self._gate._audit("SEND", lookup_ref,
                              payload={"action": "OPEN_LOOKUP",
                                       "policy_digest": proposal.policy_digest})
            outcome, owner, payload = self._port.lookup_open_with_payload(
                request, order_id=acceptance.order_id, reference_id=lookup_ref)
            envelope = self._gate._adapter.seal_open_lookup_or_unresolved(
                payload, request=request, observed_at=self._gate._clock(),
                accepted_order_id=acceptance.order_id)
            self._gate._runtime.resolve(envelope)
            self._record_reconciliation(proposal.reference_id, "OPEN", envelope)
            if owner is not None:
                self._owners[proposal.reference_id] = owner
            return AutonomousOpenResult(
                "SIMULATED_POSITION_OPEN" if owner is not None else outcome.status,
                acceptance.order_id, owner, envelope)
        except Exception as exc:
            self._halt_ambiguous("AUTONOMOUS_OPEN_UNRESOLVED")
            raise SD138Refused("autonomous open stopped for reconciliation") from exc

    def recover_entry(self, proposal: EntryProposal) -> AutonomousOpenResult:
        """GET-only restart recovery; never repeats an open POST."""
        request = self._open_request(proposal)
        book_id = self._book_for(proposal)
        entry = self._gate._runtime.ledger.state().entries.get(proposal.reference_id)
        if entry is None:
            raise SD138Refused("policy ledger has no durable entry proposal")
        if (entry.track, entry.canonical_id, entry.instrument, entry.units, entry.limit) != (
                proposal.track, proposal.canonical_id, proposal.etoro_instrument_id,
                proposal.units, proposal.limit_price):
            raise SD138Refused("restart proposal differs from the durable policy intent")
        recovery_ref = f"recovery:{request.reference_id}"
        self._gate._authorize(write=False, reference_id=recovery_ref)
        self._gate._audit("SEND", recovery_ref,
                          payload={"action": "OPEN_RECOVERY",
                                   "policy_digest": proposal.policy_digest,
                                   "book_id": book_id})
        try:
            outcome, owner, payload = self._port.lookup_open_with_payload(
                request, reference_id=recovery_ref)
            envelope = self._gate._adapter.seal_open_lookup_or_unresolved(
                payload, request=request, observed_at=self._gate._clock(),
                accepted_order_id=outcome.order_id)
            if entry.outcome in _UNKNOWN_OUTCOMES:
                if outcome.status == "UNRESOLVED":
                    self._gate._runtime.ledger.trip_kill_switch(
                        "AUTONOMOUS_OPEN_RECOVERY_UNRESOLVED", self._gate._clock())
                else:
                    self._gate._runtime.reconcile_unknown(envelope)
            else:
                self._gate._runtime.resolve(envelope)
            self._record_reconciliation(proposal.reference_id, "OPEN_RECOVERY", envelope)
            if owner is not None:
                self._owners[proposal.reference_id] = owner
            return AutonomousOpenResult(
                "SIMULATED_POSITION_OPEN" if owner is not None else outcome.status,
                outcome.order_id, owner, envelope)
        except Exception as exc:
            self._halt_ambiguous("AUTONOMOUS_OPEN_RECOVERY_UNRESOLVED")
            raise SD138Refused("open recovery failed closed; no POST was repeated") from exc

    def submit_exit(self, proposal: ExitProposal, *, quote: Envelope) -> AutonomousCloseResult:
        """Simulate one full close and independently authorised final whole-account GET."""
        request, protective = self._gate.validate_exit_at_send(proposal, quote=quote)
        owner = self._owners.get(proposal.entry_reference)
        if owner is None or owner.position_id != request.position_id:
            raise SD138Refused("close requires this adapter's verified open lineage")
        book_id = self._book_for_entry(proposal.entry_reference)
        self._gate._audit(
            "ORDER_RESERVATION", proposal.reference_id,
            payload={"action": "CLOSE", "policy_digest": proposal.policy_digest,
                     "book_id": book_id, "units": str(proposal.units),
                     "instrument_id": proposal.etoro_instrument_id,
                     "position_id": request.position_id},
        )
        self._gate._authorize(write=True, reference_id=request.reference_id,
                              protective=protective)
        try:
            self._gate._audit("SEND", request.reference_id,
                              payload={"action": "CLOSE", "policy_digest": proposal.policy_digest,
                                       "book_id": book_id,
                                       "intent_reference": proposal.reference_id})
            accepted = self._port.submit_owned_close(
                request, owner=owner, intent_id=proposal.reference_id, book_id=book_id)
            close_lookup_ref = f"close-lookup:{request.reference_id}"
            self._gate._authorize(write=False, reference_id=close_lookup_ref,
                                  protective=protective)
            self._gate._audit("SEND", close_lookup_ref,
                              payload={"action": "CLOSE_LOOKUP",
                                       "policy_digest": proposal.policy_digest})
            result = self._port.lookup_close(accepted, request=request, owner=owner,
                                             reference_id=close_lookup_ref)
            if (result.outcome.status != "FILLED"
                    or result.outcome.closed_units != owner.remaining_units):
                raise SD138Refused("close-info did not report the full owned position closed")

            pnl_reference = f"close-pnl:{request.reference_id}"
            self._gate._authorize(write=False, reference_id=pnl_reference,
                                  protective=protective)
            self._gate._audit("SEND", pnl_reference,
                              payload={"action": "FINAL_PORTFOLIO_RECONCILIATION",
                                       "policy_digest": proposal.policy_digest,
                                       "book_id": book_id,
                                       "position_id": request.position_id,
                                       "close_order_id": accepted.order_id})
            payload = self._port.read_demo_portfolio(reference_id=pnl_reference)
            observed_at = self._gate._clock()
            snapshot = parse_demo_portfolio(payload, observed_at=observed_at)
            snapshot.require_fresh(observed_at)
            baseline = self._port.baseline_position_ids
            observed_ids = {position.position_id for position in snapshot.positions}
            if (len(baseline) != 4 or observed_ids != set(baseline)
                    or request.position_id in observed_ids or snapshot.pending_orders
                    or snapshot.mirror_count != 0):
                raise SD138Refused(
                    "final fake portfolio does not show exactly the protected four-position baseline")

            # Only the exact offline simulator exposes fixture economics; the typed
            # production-shaped close-info response itself has no execution price.
            simulated_price: Decimal | None = self._port.simulated_close_fill_price(
                accepted.order_id)
            if simulated_price is None:
                raise SD138Refused("offline simulator has no full-close price evidence")
            evidence = self._gate._adapter.seal_simulated_close(
                payload=result.payload,
                request=request, acceptance=accepted, observed_at=observed_at,
                fill_price=simulated_price,
            )
            self._gate._audit(
                "RECONCILIATION", proposal.reference_id,
                payload={"action": "FINAL_PNL_SIMULATION",
                         "snapshot_sha256": snapshot.payload_sha256,
                         "baseline_position_ids": sorted(baseline),
                         "close_order_id": accepted.order_id,
                         "simulated_close_price": str(simulated_price)},
            )
            self._gate._publish_before_send(self._gate._clock())
            self._port.reconcile_full_close(
                reference_id=request.reference_id, order_id=accepted.order_id,
                position_id=request.position_id, closed_units=result.outcome.closed_units,
            )
            self._gate._runtime.resolve(evidence)
            return AutonomousCloseResult(result, snapshot.payload_sha256,
                                         tuple(sorted(baseline)))
        except Exception as exc:
            self._halt_ambiguous("AUTONOMOUS_CLOSE_UNRESOLVED")
            raise SD138Refused("autonomous close stopped for reconciliation") from exc

    def _book_for_entry(self, reference_id: str) -> str:
        state = self._gate._runtime.ledger.state()
        entry = state.entries.get(reference_id)
        if entry is None:
            raise SD138Refused("close has no durable policy entry")
        # The same signed strategy scope that authorized the opening owns its close.
        try:
            return self._gate._policy.book_for_track(entry.track)
        except Exception as exc:
            raise SD138Refused("entry track has ambiguous signed book ownership") from exc

    def _halt_ambiguous(self, reason: str) -> None:
        try:
            if not self._gate._runtime.ledger.kill_switch_engaged():
                self._gate._runtime.ledger.trip_kill_switch(reason, self._gate._clock())
            self._gate._publish_before_send(self._gate._clock())
        except Exception as exc:
            raise SD138Refused("HALT checkpoint could not be anchored") from exc
