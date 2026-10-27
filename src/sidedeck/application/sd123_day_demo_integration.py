"""Offline Day Trader -> policy-bound Demo integration seam.

This module connects the approved-input boundary to the existing native ORB method,
independent SD-071 admission and SD-072 sizing.  It deliberately stops before broker
transport: callers receive a proposal-only result unless an explicitly labelled fixture
override is used by an offline acceptance test.  No data entitlement is inferred from an
eToro-shaped payload and no broker route is enabled here.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from sidedeck.application.sd069_day_trader_methods import orb_signal
from sidedeck.application.sd070_research_signal import ResearchSignal
from sidedeck.application.sd071_decision_engine import StrategyAdmission
from sidedeck.application.sd122_etoro_intraday_bridge import (
    research_bars_from_etoro_sample,
)

STRATEGY_ID = "day-trader-skill.orb"
STRATEGY_VERSION = "sd069-native-1"


@dataclass(frozen=True)
class DayResearchResult:
    signal: ResearchSignal | None
    admission: StrategyAdmission
    metadata: dict[str, Any]
    status: str


def research_day_sample(
    payload: Mapping[str, Any], *, instrument_id: int, symbol: str,
    cutoff: datetime, generated_at: datetime,
) -> DayResearchResult:
    """Run native DAY research on a strictly parsed eToro-shaped sample.

    The result remains ``RESEARCH_ONLY`` because SD-122 midpoint data is explicitly
    unverified and non-executable.  The independent admission object is still returned so
    SD-071 can prove that a signal cannot qualify merely because the method triggered.
    """
    bars, metadata = research_bars_from_etoro_sample(
        payload, instrument_id=instrument_id, symbol=symbol, cutoff=cutoff,
    )
    signal = orb_signal(f"US:XNAS:{symbol}", bars, generated_at)
    if signal is None:
        admission = StrategyAdmission(
            STRATEGY_ID, STRATEGY_VERSION, "DAY", "RESEARCH_ONLY",
            "sd122://unverified", 0, False,
        )
        return DayResearchResult(None, admission, metadata, "NO_SIGNAL")
    admission = StrategyAdmission(
        STRATEGY_ID, STRATEGY_VERSION, "DAY", "RESEARCH_ONLY",
        f"sd122://{metadata['source_payload_sha256']}", 0, False,
    )
    return DayResearchResult(signal, admission, metadata, "RESEARCH_ONLY")


def admit_fixture_day_strategy(*, evidence_ref: str, oos_trades: int,
                               oos_validated: bool, fixture_acceptance: bool = False
                               ) -> StrategyAdmission:
    """Create an admission only for a labelled offline acceptance fixture.

    Production callers must provide a separately verified locked-OOS evidence record; this
    helper refuses to turn the unverified SD-122 market-data sample into a live admission.
    """
    if fixture_acceptance is not True:
        raise PermissionError("DAY strategy admission requires explicit fixture_acceptance=True")
    if not evidence_ref.strip():
        raise ValueError("independent admission evidence reference is required")
    return StrategyAdmission(
        STRATEGY_ID, STRATEGY_VERSION, "DAY", "ADMITTED", evidence_ref,
        oos_trades, oos_validated,
    )


def release_status() -> dict[str, str]:
    """Expose the unchanged release boundary for operator/reporting surfaces."""
    return {
        "data_admission": "BLOCKED_EXTERNAL",
        "strategy_admission": "BLOCKED_EXTERNAL",
        "broker_route": "ETORO_DEMO_NOT_RELEASED",
        "etoro_real": "PERMANENTLY_EXCLUDED",
        "execution_permission": "NOT_GRANTED_BY_DECISION_ENGINE",
    }
