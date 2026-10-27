"""SD-126: one *offline* DAY decision/exit cycle through SD-107.

Unattended orchestration can reuse this seam after independent admission and
a separately reviewed broker transport are released. This implementation
accepts only OfflineDemoGateway, never imports HTTP/.env and never transmits
an order. Every send remains subject to SD-063/064/074/107 independently.

Exits are processed first. A new entry is never sent in a cycle where any
exit was required or unresolved. Ambiguous results halt without retrying.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sidedeck.application.sd063_autonomous_demo_policy import EntryProposal, Refusal
from sidedeck.application.sd074_trusted_inputs import AuthenticatedRuntime, Envelope
from sidedeck.application.sd107_demo_gateway import (
    BROKER_ROUTES, OfflineDemoGateway,
)


@dataclass(frozen=True)
class DayCycleResult:
    status: str
    entry_reference: str | None
    exit_references: tuple[str, ...]
    alerts: tuple[str, ...]
    open_positions: int
    broker_route: str = "SIMULATED_LOCAL"
    execution_release: str = "ETORO_DEMO_NOT_RELEASED"

    def report(self) -> dict[str, Any]:
        return {
            "schema": "sidedeck.sd126.offline-day-cycle/1",
            "status": self.status, "entry_reference": self.entry_reference,
            "exit_references": list(self.exit_references),
            "alerts": list(self.alerts), "open_positions": self.open_positions,
            "broker_route": self.broker_route,
            "execution_release": self.execution_release,
        }


class OfflineDayCycleController:
    """Operate SD-107's tested local simulator, with fail-closed exit priority."""

    def __init__(
        self, runtime: AuthenticatedRuntime, gateway: OfflineDemoGateway, *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if type(runtime) is not AuthenticatedRuntime or type(gateway) is not OfflineDemoGateway:
            raise TypeError("only SD-074 and the exact offline SD-107 gateway are accepted")
        if gateway._runtime is not runtime or BROKER_ROUTES != {"ETORO_DEMO": "NOT_RELEASED"}:
            raise PermissionError("Day Trader cannot choose or activate a broker transport")
        self.runtime, self.gateway, self.clock = runtime, gateway, clock

    def _result(
        self, status: str, entry: str | None, exits: list[str], alerts: list[str],
    ) -> DayCycleResult:
        return DayCycleResult(
            status, entry, tuple(exits), tuple(alerts),
            len(self.runtime.ledger.open_positions()),
        )

    def _halt(self, reason: str) -> None:
        when = self.clock()
        if when.tzinfo is None or when.utcoffset() is None:
            raise ValueError("controller clock is not timezone-aware")
        if not self.runtime.ledger.kill_switch_engaged():
            self.runtime.ledger.trip_kill_switch(reason, when.astimezone(UTC))

    def tick(
        self, *,
        planning_bids: Sequence[Envelope] = (),
        execution_bids: Mapping[str, Envelope] | None = None,
        entry: EntryProposal | Refusal | None = None,
        entry_quote: Envelope | None = None,
        entry_marks: Sequence[Envelope] = (),
    ) -> DayCycleResult:
        """Handle exits before one already-policy-validated entry proposal.

        Planning and execution require distinct sealed quote envelopes with
        unique nonces. A replay cannot be used as authorization for a new send.
        Inputs and owner-signed policy are validated by the existing components.
        """
        exits: list[str] = []
        alerts: list[str] = []
        if execution_bids is None:
            execution_bids = {}
        plan = self.runtime.plan_exits(bids=planning_bids)
        alerts.extend(plan.alerts)
        for proposal in plan.exits:
            if proposal.track != "DAY":
                self._halt("DAY_CYCLE_FOREIGN_TRACK_EXIT")
                return self._result("HALTED", None, exits,
                                    alerts + ["FOREIGN_TRACK_EXIT_REFUSED"])
            fresh = execution_bids.get(proposal.canonical_id)
            if fresh is None:
                self._halt("DAY_CYCLE_EXIT_QUOTE_MISSING")
                return self._result("HALTED", None, exits,
                                    alerts + ["EXIT_SEND_QUOTE_MISSING"])
            try:
                evidence = self.gateway.submit_exit(proposal, quote=fresh)
            except Exception as exc:
                # A missing/ambiguous broker acknowledgement is *never* an
                # invitation to replay a close. Operator reconciliation only.
                self._halt("DAY_CYCLE_EXIT_NOT_CONFIRMED")
                return self._result("HALTED", None, exits,
                                    alerts + [f"EXIT_NOT_CONFIRMED:{type(exc).__name__}"])
            exits.append(proposal.reference_id)
            if evidence.payload.get("outcome") != "FILLED":
                self._halt("DAY_CYCLE_EXIT_UNRESOLVED")
                return self._result("HALTED", None, exits, alerts + ["EXIT_UNRESOLVED"])
        if exits:
            # Avoid close/open churn within one tick, even when cash is freed.
            return self._result(
                "EXITS_CONFIRMED" if not self.runtime.ledger.open_positions()
                else "EXITS_PROCESSED", None, exits, alerts,
            )
        if self.runtime.ledger.kill_switch_engaged():
            return self._result("HALTED", None, exits, alerts + ["KILL_SWITCH_ENGAGED"])
        if alerts:
            # Missing/stale marks, pending or quarantined exits and protective
            # exceptions all block the entry path until reconciled.
            return self._result("ATTENTION_REQUIRED", None, exits, alerts)
        if entry is None:
            return self._result("NO_TRADE", None, exits, alerts)
        if isinstance(entry, Refusal):
            return self._result("NO_TRADE", None, exits, alerts + list(entry.reasons))
        if not isinstance(entry, EntryProposal) or entry.track != "DAY":
            return self._result("NO_TRADE", None, exits, alerts + ["NON_DAY_PROPOSAL_REFUSED"])
        if entry_quote is None:
            self._halt("DAY_CYCLE_ENTRY_QUOTE_MISSING")
            return self._result("HALTED", entry.reference_id, exits,
                                alerts + ["ENTRY_SEND_QUOTE_MISSING"])
        row = self.runtime.ledger.state().entries.get(entry.reference_id)
        if row is None:
            return self._result("NO_TRADE", None, exits, alerts + ["NOT_DURABLY_PROPOSED"])
        if row.outcome is not None:
            # Never resubmit an accepted or already resolved proposal. This
            # also holds after restart with the same policy/ledger state.
            return self._result(
                "NO_TRADE", None, exits, alerts + ["ENTRY_ALREADY_RESOLVED"],
            )
        try:
            evidence = self.gateway.submit_entry(
                entry, quote=entry_quote, marks=tuple(entry_marks),
            )
        except Exception as exc:
            self._halt("DAY_CYCLE_ENTRY_NOT_CONFIRMED")
            return self._result("HALTED", entry.reference_id, exits,
                                alerts + [f"ENTRY_NOT_CONFIRMED:{type(exc).__name__}"])
        if evidence.payload.get("outcome") != "FILLED":
            self._halt("DAY_CYCLE_ENTRY_UNRESOLVED")
            return self._result("HALTED", entry.reference_id, exits,
                                alerts + ["ENTRY_UNRESOLVED"])
        return self._result("ENTRY_CONFIRMED", entry.reference_id, exits, alerts)
