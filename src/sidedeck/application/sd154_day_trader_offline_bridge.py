"""SD-154: connect Day Trader research to the existing offline DAY execution seam.

No upstream skill ticket may be forwarded as an order. An ORB method observation
is research-only; a separately admitted, sealed native strategy signal is
necessary for an entry. SD-074 and SD-126 retain all proposal and order checks.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sidedeck.application.sd063_autonomous_demo_policy import EntryProposal, Refusal
from sidedeck.application.sd071_decision_engine import StrategyAdmission
from sidedeck.application.sd074_trusted_inputs import Envelope
from sidedeck.application.sd123_day_demo_integration import (
    STRATEGY_ID, STRATEGY_VERSION, DayResearchResult,
)
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


def _cutoff_covers_orb(value: Any, orb_cutoff: datetime) -> bool:
    """Require native evidence to cover the completed ORB, without trusting it as proof."""
    if type(value) is not str:
        return False
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError:
        return False
    return timestamp.tzinfo is not None and orb_cutoff <= timestamp


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
          or research_result.signal.source_id != STRATEGY_ID
          or research_result.signal.source_version != STRATEGY_VERSION
          or research_result.admission.track != research_result.signal.track
          or research_result.admission.strategy_id != research_result.signal.source_id
          or research_result.admission.version != research_result.signal.source_version
          or research_result.admission.status != "RESEARCH_ONLY"):
        reasons = ("UNTRUSTED_DAY_TRADER_RESEARCH",)
    elif (
        research_result.signal.generated_at > controller.clock()
        or controller.clock() - research_result.signal.generated_at > timedelta(minutes=15)
        or research_result.signal.data_cutoff > controller.clock()
        or controller.clock() - research_result.signal.data_cutoff > timedelta(minutes=15)
    ):
        reasons = ("STALE_OR_FUTURE_DAY_TRADER_RESEARCH",)
    elif not native_signals or not admissions:
        reasons = ("INDEPENDENT_NATIVE_STRATEGY_ADMISSION_REQUIRED",)
    elif any(
        type(signal) is not Envelope
        or signal.kind != "signal"
        or type(signal.payload) is not dict
        or signal.payload.get("source_kind") != "NATIVE_STRATEGY"
        or signal.payload.get("canonical_id") != research_result.signal.canonical_id
        or signal.payload.get("track") != "DAY"
        or signal.payload.get("direction") != research_result.signal.direction
        or not _cutoff_covers_orb(signal.payload.get("data_cutoff"),
                                 research_result.signal.data_cutoff)
        for signal in native_signals
    ):
        # The independent native runner must describe the *same* opportunity;
        # its authenticity and strategy admission are still checked by SD-074.
        reasons = ("DAY_TRADER_NATIVE_SIGNAL_MISMATCH",)
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
