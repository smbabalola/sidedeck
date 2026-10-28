"""SD-140: fail-closed SWING lifecycle through the existing SD-138 fake broker.

No credentials, network client, new trading engine or permission to send actual
orders. Planning quotes and send-time quotes must be independent sealed inputs.
Protective exits are considered before any new entry. Caller cannot promote a
research-only or DAY strategy into an executable SWING order.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sidedeck.application.sd063_autonomous_demo_policy import EntryProposal, Refusal
from sidedeck.application.sd068_track_scheduler import NEW_YORK, SchedulerError, session_for
from sidedeck.application.sd074_trusted_inputs import AuthenticatedRuntime, Envelope
from sidedeck.application.sd107_demo_gateway import BROKER_ROUTES
from sidedeck.application.sd138_autonomous_order_adapter import (
    AutonomousEtoroDemoOrderAdapter,
)


@dataclass(frozen=True)
class SwingCycleResult:
    status: str
    entry_reference: str | None
    exit_references: tuple[str, ...]
    alerts: tuple[str, ...]
    open_positions: int
    broker_route: str = "SIMULATED_LOCAL"
    execution_release: str = "ETORO_DEMO_NOT_RELEASED"

    def report(self) -> dict[str, Any]:
        return {
            "schema": "sidedeck.sd140.offline-swing-cycle/1",
            "status": self.status,
            "entry_reference": self.entry_reference,
            "exit_references": list(self.exit_references),
            "alerts": list(self.alerts),
            "open_positions": self.open_positions,
            "broker_route": self.broker_route,
            "execution_release": self.execution_release,
        }


class OfflineSwingCycleController:
    """Run at most one risk-gated SWING entry or all due exits per scheduled cycle.

    The provided adapter is *exactly* SD-138's offline fake composition, rather
    than a broker interface injected by an untrusted research agent.
    """

    def __init__(
        self,
        runtime: AuthenticatedRuntime,
        adapter: AutonomousEtoroDemoOrderAdapter,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if type(runtime) is not AuthenticatedRuntime or type(adapter) is not AutonomousEtoroDemoOrderAdapter:
            raise TypeError("SD-140 requires exact SD-074 and SD-138 offline components")
        if (adapter._gate._runtime is not runtime
                or not adapter._port.is_offline_fake_route
                or BROKER_ROUTES != {"ETORO_DEMO": "NOT_RELEASED"}):
            raise PermissionError("SD-140 cannot activate a broker transport")
        self.runtime, self.adapter, self.clock = runtime, adapter, clock

    def _result(
        self, status: str, entry: str | None,
        exits: list[str], alerts: list[str],
    ) -> SwingCycleResult:
        return SwingCycleResult(
            status, entry, tuple(exits), tuple(alerts),
            len(self.runtime.ledger.open_positions()),
        )

    def _halt(self, reason: str) -> None:
        self.adapter._halt_ambiguous(reason)

    def tick(
        self, *,
        planning_bids: Sequence[Envelope] = (),
        execution_bids: Mapping[str, Envelope] | None = None,
        entry: EntryProposal | Refusal | None = None,
        entry_quote: Envelope | None = None,
        entry_marks: Sequence[Envelope] = (),
    ) -> SwingCycleResult:
        now = self.clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("SWING cycle clock must be timezone-aware")
        try:
            session = session_for(now.astimezone(NEW_YORK).date())
        except SchedulerError:
            self._halt("SWING_CALENDAR_UNCOVERED")
            return self._result("HALTED", None, [], ["CALENDAR_UNCOVERED"])
        if session is None or not session.open_utc <= now < session.close_utc:
            # Positions are not assumed flat outside the session. The policy's
            # plan-exits / next market session must handle overnight exposure.
            return self._result("OUT_OF_SESSION", None, [],
                                ["NO_US_EQUITY_EXECUTION_SESSION"])

        plan = self.runtime.plan_exits(bids=planning_bids)
        exits: list[str] = []
        alerts = list(plan.alerts)
        for proposal in plan.exits:
            if proposal.track != "SWING":
                self._halt("SWING_FOREIGN_TRACK_EXIT")
                return self._result("HALTED", None, exits,
                                    alerts + ["FOREIGN_TRACK_EXIT_REFUSED"])
            quote = (execution_bids or {}).get(proposal.canonical_id)
            if quote is None:
                self._halt("SWING_EXIT_SEND_QUOTE_MISSING")
                return self._result("HALTED", None, exits,
                                    alerts + ["EXIT_SEND_QUOTE_MISSING"])
            try:
                result = self.adapter.submit_exit(proposal, quote=quote)
            except Exception as exc:
                self._halt("SWING_EXIT_UNRESOLVED")
                return self._result("HALTED", None, exits,
                                    alerts + [f"EXIT_UNRESOLVED:{type(exc).__name__}"])
            exits.append(proposal.reference_id)
            if result.outcome.status != "FILLED":
                self._halt("SWING_EXIT_NOT_FULLY_FILLED")
                return self._result("HALTED", None, exits,
                                    alerts + ["EXIT_NOT_FULLY_FILLED"])
        if exits:
            return self._result(
                "EXITS_CONFIRMED" if not self.runtime.ledger.open_positions()
                else "EXITS_PROCESSED", None, exits, alerts,
            )

        if self.runtime.ledger.kill_switch_engaged():
            return self._result("HALTED", None, exits,
                                alerts + ["KILL_SWITCH_ENGAGED"])
        if alerts:
            # An already-owned position needs functioning protective monitoring:
            # audit/quote/ownership/pending-exit failures cannot be a soft
            # "attention" status that permits an unattended later tick.
            if self.runtime.ledger.open_positions():
                self._halt("SWING_POSITION_PROTECTION_UNVERIFIED")
                return self._result("HALTED", None, exits,
                                    alerts + ["POSITION_PROTECTION_UNVERIFIED"])
            return self._result("ATTENTION_REQUIRED", None, exits, alerts)
        if self.runtime.ledger.open_positions():
            # First vertical slice: one owned SWING position at a time.
            return self._result("MONITORING", None, exits, alerts)
        if entry is None:
            return self._result("NO_TRADE", None, exits, alerts)
        if isinstance(entry, Refusal):
            return self._result("NO_TRADE", None, exits,
                                alerts + list(entry.reasons))
        if not isinstance(entry, EntryProposal) or entry.track != "SWING":
            return self._result("NO_TRADE", None, exits,
                                alerts + ["NON_SWING_PROPOSAL_REFUSED"])
        row = self.runtime.ledger.state().entries.get(entry.reference_id)
        if row is None or row.outcome is not None:
            return self._result("NO_TRADE", None, exits,
                                alerts + ["NO_NEW_DURABLE_ENTRY"])
        if entry_quote is None:
            self._halt("SWING_ENTRY_SEND_QUOTE_MISSING")
            return self._result("HALTED", entry.reference_id, exits,
                                alerts + ["ENTRY_SEND_QUOTE_MISSING"])
        try:
            opened = self.adapter.submit_entry(
                entry, quote=entry_quote, marks=tuple(entry_marks),
            )
        except Exception as exc:
            self._halt("SWING_ENTRY_UNRESOLVED")
            return self._result("HALTED", entry.reference_id, exits,
                                alerts + [f"ENTRY_UNRESOLVED:{type(exc).__name__}"])
        if opened.position is None:
            self._halt("SWING_ENTRY_FILL_UNVERIFIED")
            return self._result("HALTED", entry.reference_id, exits,
                                alerts + ["ENTRY_FILL_UNVERIFIED"])
        return self._result("ENTRY_CONFIRMED", entry.reference_id, exits, alerts)
