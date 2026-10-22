"""SD-069 adapters: TradingAgents / AI Hedge Fund (BuffettAgent) outputs -> ResearchSignal.

Input is the per-agent record emitted by ``p5_agents`` (research-only). The
adapter is the *trusted channel*: it knows which upstream it invoked and its
pinned revision, and refuses records claiming anything else. Abstentions and
unavailable/blocked runs are preserved as outcomes, never dropped and never
turned into directional opinions. Agent signals are capped at WATCHLIST by the
SD-071 decision engine. This module makes no model or network call.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Mapping

from sidedeck.application.p5_agents import AI_HEDGE_FUND_REVISION, TRADINGAGENTS_REVISION
from sidedeck.application.sd070_research_signal import EvidenceRef, ResearchSignal, SignalError


@dataclass(frozen=True)
class AgentProfile:
    portfolio: str
    upstream: str
    revision: str
    source_kind: str
    source_id: str
    track: str
    horizon: tuple[int, int]


PROFILES: dict[str, AgentProfile] = {
    "tradingagents": AgentProfile("tradingagents", "TauricResearch/TradingAgents",
                                  TRADINGAGENTS_REVISION, "TRADINGAGENTS", "tradingagents",
                                  "SWING", (2, 15)),
    "ai-trading": AgentProfile("ai-trading", "virattt/ai-hedge-fund", AI_HEDGE_FUND_REVISION,
                               "AI_HEDGE_FUND", "ai_hedge_fund.buffett", "POSITION", (20, 180)),
}
_DIRECTION = {"BUY": "LONG", "SELL": "SHORT", "HOLD": "NEUTRAL"}
PROCEDURAL_INVALIDATION = (
    "SIDEDECK_PROCEDURAL: superseded when a re-run on newer data changes or abstains",
    "SIDEDECK_PROCEDURAL: superseded when newer filings or prices post-date the data cutoff",
)


@dataclass(frozen=True)
class AgentOutcome:
    portfolio: str
    canonical_id: str | None
    status: str  # SIGNAL | ABSTAINED | UNAVAILABLE | REFUSED
    reason: str
    signal: ResearchSignal | None
    output_sha256: str


def _digest(record: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(record, sort_keys=True, default=str).encode()).hexdigest()


def adapt_agent_record(
    record: Mapping[str, Any], *, invoked: str, allowed_ids: Iterable[str], now: datetime,
) -> AgentOutcome:
    """Convert one ``p5_agents`` record from the adapter that ``invoked`` it."""
    profile = PROFILES.get(invoked)
    if profile is None:
        raise SignalError(f"unknown agent adapter {invoked}")
    sha = _digest(record)
    cid = record.get("instrument_id") or (
        "US:" + str(record["ticker"]) if record.get("ticker") else None)

    def outcome(status: str, reason: str, signal: ResearchSignal | None = None) -> AgentOutcome:
        return AgentOutcome(profile.portfolio, cid, status, reason, signal, sha)

    if record.get("portfolio") != profile.portfolio or record.get("upstream") != profile.upstream:
        return outcome("REFUSED", "record identity does not match the invoking adapter")
    if record.get("status") == "BLOCKED" or record.get("unavailable"):
        return outcome("UNAVAILABLE", str(record.get("reason", "agent unavailable"))[:200])
    ticker = record.get("ticker")
    if ticker and record.get("instrument_id") and record["instrument_id"] != f"US:{ticker}":
        return outcome("REFUSED", "instrument_id and ticker disagree")
    if cid is None or cid not in set(allowed_ids):
        return outcome("REFUSED", "instrument was not on the research shortlist")
    if record.get("upstream_version") != profile.revision:
        return outcome("REFUSED", "upstream version differs from the pinned revision")
    try:
        cutoff = datetime.fromisoformat(str(record["market_cutoff"]))
        generated = datetime.fromisoformat(str(record["decision_timestamp"]))
    except (KeyError, ValueError):
        return outcome("REFUSED", "data cutoff and decision timestamp are required")
    fingerprint = str(record.get("model_config_fingerprint", ""))[:12]
    model = f"{record.get('model_provider', '')}/{record.get('model_id', '')}"
    source_version = f"{profile.revision}|{model}|cfg:{fingerprint}"
    abstained = bool(record.get("abstained"))
    direction = "ABSTAIN" if abstained else _DIRECTION.get(str(record.get("decision")), "")
    if not direction:
        return outcome("REFUSED", "decision must be BUY, SELL or HOLD")
    evidence = (EvidenceRef("agent_output", f"{profile.portfolio}:{cid}", sha),) + tuple(
        EvidenceRef("agent_reference_text", str(ref)[:200],
                    hashlib.sha256(str(ref).encode()).hexdigest())
        for ref in record.get("evidence_references", ()) if str(ref).strip()
    )
    try:
        signal = ResearchSignal(
            canonical_id=cid, track=profile.track, source_kind=profile.source_kind,
            source_id=profile.source_id, source_version=source_version,
            horizon_min_days=profile.horizon[0], horizon_max_days=profile.horizon[1],
            direction=direction, evidence=evidence, generated_at=generated, data_cutoff=cutoff,
            invalidation=PROCEDURAL_INVALIDATION if direction in ("LONG", "SHORT") else (),
            rationale=str(record.get("rationale", ""))[:2000],
        )
    except SignalError as exc:
        return outcome("REFUSED", str(exc))
    if signal.generated_at > now:
        return outcome("REFUSED", "decision timestamp is in the future")
    return outcome("ABSTAINED" if abstained else "SIGNAL", "ok", signal)


def research_candidates(shortlist_ids: Iterable[str], already_researched: Iterable[str],
                        limit: int) -> tuple[str, ...]:
    """Agents run on the research shortlist only, bounded, without repeats."""
    if not 0 < limit <= 30:
        raise SignalError("research batch must be 1-30 instruments")
    done = set(already_researched)
    return tuple(cid for cid in shortlist_ids if cid not in done)[:limit]
