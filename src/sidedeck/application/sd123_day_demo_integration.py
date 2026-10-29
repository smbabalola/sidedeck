"""SD-123: offline Day Trader research and independently gated Demo admission.

The signed, owner-released Demo order route is separate. Imported eToro-shaped
midpoint bars are unverified research data and never execution quotes.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from sidedeck.application.sd065_market_universe import (
    MarketUniverseRegistry, UniverseError,
)
from sidedeck.application.sd068_track_scheduler import NEW_YORK, session_for
from sidedeck.application.sd069_day_trader_methods import (
    METHOD_VERSION, orb_signal,
)
from sidedeck.application.sd070_research_signal import ResearchSignal
from sidedeck.application.sd071_decision_engine import StrategyAdmission
from sidedeck.application.sd122_etoro_intraday_bridge import (
    research_bars_from_etoro_sample,
)

STRATEGY_ID = "day_trader_skill.orb"
STRATEGY_VERSION = METHOD_VERSION


@dataclass(frozen=True)
class DayResearchResult:
    signal: ResearchSignal | None
    admission: StrategyAdmission
    metadata: dict[str, Any]
    status: str


def _resolve_research_identity(
    registry: MarketUniverseRegistry, *, symbol: str, instrument_id: int,
    cutoff: datetime,
) -> tuple[str, str]:
    """Resolve as-of listing, not a fabricated venue or source-provided ID."""
    as_of = cutoff.astimezone(NEW_YORK).date()
    try:
        record = registry.resolve(symbol, as_of)
    except UniverseError as exc:
        raise ValueError("instrument is absent or ambiguous in the point-in-time registry") from exc
    listing = record.ticker_on(as_of)
    if (not record.listed_on(as_of) or record.suspended_on(as_of)
            or listing is None or listing.ticker != symbol
            or record.market_id != "US"
            or record.asset_type not in ("ETF", "COMMON_STOCK")):
        raise ValueError("instrument is not a verified current US stock/ETF listing")

    # A verified conflicting broker map is reason to refuse even research, not to
    # choose whichever ID came from the latest API response.
    mappings = [m for m in record.broker_mappings
                if m.broker == "ETORO" and m.environment == "DEMO" and m.verified]
    if len(mappings) > 1 or any(m.broker_instrument_id != str(instrument_id)
                                for m in mappings):
        raise ValueError("eToro instrument identity conflicts with verified registry mapping")
    return record.canonical_id, "VERIFIED" if len(mappings) == 1 else "UNVERIFIED"


def research_day_sample(
    payload: Mapping[str, Any], *, instrument_id: int, symbol: str,
    cutoff: datetime, generated_at: datetime, registry: MarketUniverseRegistry,
) -> DayResearchResult:
    """Research on a strict local 5m sample, never an execution-ready strategy.

    The registry must be supplied by the caller: an eToro payload cannot claim its
    own canonical listing identity, admission status or broker mapping.
    """
    if (cutoff.tzinfo is None or cutoff.utcoffset() is None
            or generated_at.tzinfo is None or generated_at.utcoffset() is None
            or generated_at < cutoff):
        raise ValueError("research requires ordered timezone-aware cutoff and generation times")
    canonical_id, broker_map = _resolve_research_identity(
        registry, symbol=symbol, instrument_id=instrument_id, cutoff=cutoff,
    )
    bars, metadata = research_bars_from_etoro_sample(
        payload, instrument_id=instrument_id, symbol=symbol, cutoff=cutoff,
    )
    metadata["canonical_id"] = canonical_id
    metadata["registry_sha256"] = registry.digest
    metadata["broker_mapping"] = broker_map
    admission = StrategyAdmission(
        STRATEGY_ID, STRATEGY_VERSION, "DAY", "RESEARCH_ONLY",
        f"sd122://{metadata['source_payload_sha256']}", 0, False,
    )

    # SD-120 discovery samples can start at 10:00 ET, *after* the 09:30
    # opening range. Never call ORB with those and report a false negative,
    # or silently manufacture the absent first three completed bars.
    day = cutoff.astimezone(NEW_YORK).date()
    session = session_for(day)
    if session is None:
        return DayResearchResult(None, admission, metadata, "INSUFFICIENT_OPENING_RANGE")
    session_bars = [b for b in bars
                    if session.open_utc <= b.start < session.close_utc]
    if not session_bars or session_bars[0].start != session.open_utc:
        return DayResearchResult(None, admission, metadata, "INSUFFICIENT_OPENING_RANGE")

    signal = orb_signal(canonical_id, session_bars, cutoff)
    if signal is None:
        return DayResearchResult(None, admission, metadata, "NO_SIGNAL")
    if (signal.source_id, signal.source_version) != (STRATEGY_ID, STRATEGY_VERSION):
        raise ValueError("native DAY signal does not match the pinned admission identity")
    return DayResearchResult(signal, admission, metadata, "RESEARCH_ONLY")


def admit_fixture_day_strategy(*, evidence_ref: str, oos_trades: int,
                               oos_validated: bool, fixture_acceptance: bool = False
                               ) -> StrategyAdmission:
    """Fixture-only admission for offline acceptance, never real-data execution."""
    if fixture_acceptance is not True:
        raise PermissionError("DAY strategy admission requires explicit fixture_acceptance=True")
    if not evidence_ref.strip():
        raise ValueError("independent admission evidence reference is required")
    return StrategyAdmission(
        STRATEGY_ID, STRATEGY_VERSION, "DAY", "ADMITTED", evidence_ref,
        oos_trades, oos_validated,
    )


def release_status() -> dict[str, str]:
    """The Demo broker execution release remains entirely separate."""
    return {
        "data_admission": "BLOCKED_EXTERNAL",
        "strategy_admission": "BLOCKED_EXTERNAL",
        "broker_route": "ETORO_DEMO_NOT_RELEASED",
        "etoro_real": "PERMANENTLY_EXCLUDED",
        "execution_permission": "NOT_GRANTED_BY_DECISION_ENGINE",
    }
