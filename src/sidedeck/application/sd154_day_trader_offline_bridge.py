"""SD-154: connect Day Trader research to the existing offline DAY execution seam.

No upstream skill ticket may be forwarded as an order. An ORB method observation
is research-only; a separately admitted, sealed native strategy signal is
necessary for an entry. SD-074 and SD-126 retain all proposal and order checks.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sidedeck.application.sd063_autonomous_demo_policy import EntryProposal, Refusal
from sidedeck.application.sd071_decision_engine import StrategyAdmission
from sidedeck.application.sd074_trusted_inputs import Envelope
from sidedeck.application.sd123_day_demo_integration import DayResearchResult
from sidedeck.application.sd126_offline_day_controller import (
    DayCycleResult, OfflineDayCycleController,
)


@dataclass(frozen=True)
class DayTraderBridgeResult:
    research_status: str
    proposal_reasons: tuple[str, ...]
    cycle: DayCycleResult

    def report(self) -> dict[str, Any]:
        return {
            "schema": "sidedeck.sd154.day-trader-offline-bridge/1",
            "research_status": self.research_status,
            "proposal_reasons": list(self.proposal_reasons),
            "cycle": self.cycle.report(),
            "broker_execution": "DISABLED",
            "execution_release": "ETORO_DEMO_NOT_RELEASED",
        }


def run_day_trader_offline_cycle(
    controller: OfflineDayCycleController,
    *,
    research_result: DayResearchResult,
    native_signals: Sequence[Envelope] = (),
    admissions: Sequence[StrategyAdmission] = (),
    sealed_research: Envelope | None = None,
    planning_quote: Envelope | None = None,
    send_quote: Envelope | None = None,
    planning_bids: Sequence[Envelope] = (),
    execution_bids: dict[str, Envelope] | None = None,
    marks: Sequence[Envelope] = (),
) -> DayTraderBridgeResult:
    """Review Day Trader intelligence; exit management runs even without entry data.

    The original Day Trader signal is deliberately *not* promoted from
    DAY_TRADER_METHOD to NATIVE_STRATEGY. All entry inputs must be sealed by
    the existing trusted upstream sources. This code cannot create any.
    """
    if type(controller) is not OfflineDayCycleController:
        raise TypeError("requires exact offline DAY controller")
    if type(research_result) is not DayResearchResult:
        raise TypeError("requires Day Trader research result")
    proposal: EntryProposal | Refusal | None = None
    reasons: tuple[str, ...] = ()
    # Never reserve a new entry ahead of exit planning for an open DAY book.
    # The controller must get the entire cycle to manage existing exposure first.
    if controller.runtime.ledger.open_positions():
        reasons = ("EXISTING_POSITION_EXIT_PRIORITY",)
    elif research_result.signal is None:
        reasons = ("DAY_TRADER_NO_ENTRY_SIGNAL",)
    elif (research_result.status != "RESEARCH_ONLY"
          or research_result.signal.track != "DAY"
          or research_result.signal.source_kind != "DAY_TRADER_METHOD"
          or research_result.admission.track != research_result.signal.track
          or research_result.admission.strategy_id != research_result.signal.source_id
          or research_result.admission.version != research_result.signal.source_version
          or research_result.admission.status != "RESEARCH_ONLY"):
        reasons = ("UNTRUSTED_DAY_TRADER_RESEARCH",)
    elif not native_signals or not admissions:
        reasons = ("INDEPENDENT_NATIVE_STRATEGY_ADMISSION_REQUIRED",)
    elif sealed_research is None or planning_quote is None:
        reasons = ("TRUSTED_ENTRY_INPUTS_REQUIRED",)
    else:
        proposal = controller.runtime.propose_entry(
            track="DAY", signals=native_signals, admissions=admissions,
            research=sealed_research, quote=planning_quote, marks=marks,
        )
        if isinstance(proposal, Refusal):
            reasons = proposal.reasons
    # Exits are always evaluated first, even when Day Trader has no signal.
    cycle = controller.tick(
        planning_bids=planning_bids, execution_bids=execution_bids,
        entry=proposal if isinstance(proposal, EntryProposal) else None,
        entry_quote=send_quote, entry_marks=marks,
    )
    return DayTraderBridgeResult(research_result.status, reasons, cycle)
