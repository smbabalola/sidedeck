"""SD-092 UK equity scan: identity -> GBP normalization -> XLON scan -> signals -> decisions.

Uses SideDeck's native universe (SD-065/SD-090), scanner (SD-067, XLON calendar),
native method signals (SD-069) and decision engine (SD-071). Nothing here fetches
data, reads credentials or touches a broker. Every exclusion carries a reason.

Rules specific to the UK run:

* only ``UK`` market records are scanned, and only on the XLON calendar;
* every series is normalized from its declared unit (GBX/GBp/GBP) to GBP first;
  research thresholds below are in GBP, not USD;
* one run has one data basis; a series with another basis is excluded so that
  fixtures can never be mixed into a real-data run (or vice versa);
* the cutoff must be a *completed* LSE session at ``now`` (no intraday bar is
  treated as a close);
* DAY needs fresh, normalized bid/ask spreads; without them DAY abstains;
* the decision engine never grants execution, and without an admitted strategy
  nothing can be ELIGIBLE. That abstention is the correct outcome, not a defect.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Mapping

from sidedeck.application.sd014_strategy_engine import StrategyBar
from sidedeck.application.sd065_market_universe import MarketUniverseRegistry, evaluate_eligibility
from sidedeck.application.sd067_market_scanner import (
    ScanReport,
    Shortlist,
    TrackScoring,
    build_shortlist,
    run_broad_scan,
)
from sidedeck.application.sd069_day_trader_methods import MethodError, daily_signals
from sidedeck.application.sd070_research_signal import ResearchSignal
from sidedeck.application.sd071_decision_engine import (
    Decision,
    MarketContext,
    PortfolioState,
    StrategyAdmission,
    TrackPolicy,
    decide,
)
from sidedeck.application.sd089_exchange_calendar import XLON
from sidedeck.application.sd090_uk_market import (
    NormalizedSeries,
    QuoteInput,
    SeriesInput,
    UkMarketError,
    normalize_quote,
    normalize_series,
)

SCAN_VERSION = "sd092.uk_scan.v1"
PRICE_UNIT = "GBP"

# Research thresholds in GBP. ``min_dollar_adv`` is the scanner's generic traded-value
# field and is interpreted in the instrument's major currency (GBP) for this run.
UK_SCORING: dict[str, TrackScoring] = {
    "DAY": TrackScoring(
        "DAY", Decimal("0.50"), Decimal("20000000"), 21,
        (("unusual_volume", Decimal("0.35")), ("abs_gap", Decimal("0.25")),
         ("atr_pct", Decimal("0.20")), ("ret_5", Decimal("0.20"))),
        min_atr_pct=Decimal("0.015"), max_spread_bps=Decimal("15"), quant_size=50,
        research_size=10,
    ),
    "SWING": TrackScoring(
        "SWING", Decimal("0.20"), Decimal("2000000"), 61,
        (("rs_60", Decimal("0.30")), ("ret_20", Decimal("0.25")),
         ("unusual_volume", Decimal("0.20")), ("breakout_20", Decimal("0.15")),
         ("sweep_reversal_20", Decimal("0.10"))),
        max_atr_pct=Decimal("0.08"), quant_size=100, research_size=15,
    ),
    "POSITION": TrackScoring(
        "POSITION", Decimal("0.20"), Decimal("1000000"), 252,
        (("ret_126", Decimal("0.35")), ("rs_60", Decimal("0.25")),
         ("vol20", Decimal("-0.25")), ("ret_60", Decimal("0.15"))),
        require_above_sma200=True, quant_size=100, research_size=15,
    ),
}


class UkScanError(ValueError):
    pass


@dataclass(frozen=True)
class IdentityRow:
    canonical_id: str
    tidm: str
    isin: str | None
    name: str
    quote_unit: str | None
    source_id: str
    source_unit: str
    divisor: str
    last_close_gbp: str
    last_bar: str
    retrieved_at: str
    provenance: str
    data_basis: str


@dataclass(frozen=True)
class UkScanResult:
    cutoff: date
    data_basis: str
    universe: int
    identities: tuple[IdentityRow, ...]
    excluded: tuple[tuple[str, str], ...]
    report: ScanReport | None
    shortlists: Mapping[str, Shortlist]
    signals: tuple[ResearchSignal, ...]
    decisions: tuple[Decision, ...]
    spreads_bps: Mapping[str, Decimal] = field(default_factory=dict)

    @property
    def acceptance(self) -> str:
        if self.data_basis != "REAL_DATA":
            return "ABSTAIN_NO_GENUINE_DATA_FIXTURE_RUN"
        if self.report is None or not self.report.features:
            return "ABSTAIN_INSUFFICIENT_GENUINE_DATA"
        if not any(d.status == "ELIGIBLE" for d in self.decisions):
            return "ABSTAIN_NO_VALIDATED_STRATEGY"
        return "CANDIDATES_FOR_SEPARATE_REVIEW"

    def summary(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for d in self.decisions:
            counts[f"{d.track}:{d.status}"] = counts.get(f"{d.track}:{d.status}", 0) + 1
        return {
            "scan_version": SCAN_VERSION, "calendar": XLON.calendar_id,
            "calendar_source_status": XLON.source_status, "price_unit": PRICE_UNIT,
            "cutoff": self.cutoff.isoformat(), "data_basis": self.data_basis,
            "universe": self.universe, "identities": [vars(i) for i in self.identities],
            "excluded": [list(e) for e in self.excluded],
            "scanned": 0 if self.report is None else len(self.report.features),
            "scan_exclusions": {} if self.report is None else self.report.exclusion_counts(),
            "rankings": {
                track: [
                    {"rank": c.rank, "canonical_id": c.canonical_id, "score": str(c.score),
                     "components": {k: (None if v is None else str(v)) for k, v in c.components},
                     "missing": list(c.missing_features)}
                    for c in s.candidates
                ]
                for track, s in self.shortlists.items()
            },
            "filtered": {track: [list(f) for f in s.filtered]
                         for track, s in self.shortlists.items()},
            "signals": [
                {"canonical_id": s.canonical_id, "track": s.track, "source_id": s.source_id,
                 "source_version": s.source_version, "direction": s.direction,
                 "horizon_days": [s.horizon_min_days, s.horizon_max_days],
                 "signal_id": s.signal_id}
                for s in self.signals
            ],
            "decisions": [
                {"canonical_id": d.canonical_id, "track": d.track, "status": d.status,
                 "reasons": list(d.reasons), "execution_permission": d.execution_permission}
                for d in self.decisions
            ],
            "decision_counts": dict(sorted(counts.items())),
            "spreads_bps": {k: str(v) for k, v in sorted(self.spreads_bps.items())},
            "acceptance": self.acceptance,
            "note": "Ranking heuristics and research signals only; never an order.",
        }


def uk_policy(track: str, now: datetime, *, capital: Decimal = Decimal("1000"),
              allowed: frozenset[tuple[str, str]] = frozenset()) -> TrackPolicy:
    """Research policy in GBP for decision-engine evaluation (not an authorization)."""
    return TrackPolicy(
        policy_id=f"sd092-uk-{track.lower()}-research", track=track, virtual_capital=capital,
        max_position_pct=Decimal("0.2"), max_positions=5, max_gross_exposure_pct=Decimal("0.8"),
        max_instrument_total_pct=Decimal("0.25"), max_sector_pct=Decimal("0.4"),
        max_correlation=Decimal("0.85"), risk_per_trade_pct=Decimal("0.01"),
        stop_atr_multiple=Decimal("2"), min_notional=Decimal("10"),
        max_signal_age=timedelta(days=1), max_signal_data_age=timedelta(days=4),
        max_price_age=timedelta(days=4), expires_at=now + timedelta(days=1),
        allowed_strategies=allowed,
    )


def run_uk_scan(
    registry: MarketUniverseRegistry,
    series: Mapping[str, SeriesInput],
    cutoff: date,
    now: datetime,
    *,
    data_basis: str,
    benchmark: SeriesInput | None = None,
    quotes: Mapping[str, QuoteInput] | None = None,
    admissions: tuple[StrategyAdmission, ...] = (),
    max_quote_age: timedelta = timedelta(minutes=15),
    min_history_sessions: int = 61,
) -> UkScanResult:
    if now.tzinfo is None:
        raise UkScanError("timezone-aware time required")
    if not XLON.is_session(cutoff):
        raise UkScanError("cutoff is not an LSE session")
    if cutoff > XLON.last_completed_session(now):
        raise UkScanError("cutoff session has not closed yet; refusing a partial-day close")
    if data_basis not in ("REAL_DATA", "SYNTHETIC_FIXTURE"):
        raise UkScanError("data basis must be REAL_DATA or SYNTHETIC_FIXTURE")
    members = registry.universe_as_of(cutoff, markets=("UK",)).members
    excluded: list[tuple[str, str]] = []
    normalized: dict[str, NormalizedSeries] = {}
    identities: list[IdentityRow] = []
    for record in members:
        cid = record.canonical_id
        raw = series.get(cid)
        if raw is None:
            excluded.append((cid, "NO_SERIES"))
            continue
        if raw.data_basis != data_basis:
            excluded.append((cid, "DATA_BASIS_MISMATCH"))
            continue
        eligibility = evaluate_eligibility(
            record, cutoff, data_source=raw.source_id, min_history_sessions=min_history_sessions,
        )
        if not eligibility.strategy_eligible:
            blocking = [r for r in eligibility.reasons
                        if not r.startswith(("NO_BROKER", "BROKER_"))]
            excluded.append((cid, "NOT_ELIGIBLE:" + ",".join(blocking)))
            continue
        try:
            norm = normalize_series(raw, record, now)
        except UkMarketError as exc:
            excluded.append((cid, str(exc)))
            continue
        normalized[cid] = norm
        ticker = record.ticker_on(cutoff)
        last = norm.bars[-1]
        identities.append(IdentityRow(
            cid, ticker.ticker if ticker else "", record.isin, record.name, record.quote_unit,
            norm.source_id, norm.source_unit, str(norm.divisor), str(last.close),
            last.day.isoformat(), norm.retrieved_at.isoformat(), norm.provenance, norm.data_basis,
        ))
    spreads: dict[str, Decimal] = {}
    for cid, quote in (quotes or {}).items():
        if cid not in normalized:
            continue
        try:
            nq = normalize_quote(quote, registry.get(cid), now, max_age=max_quote_age)
        except UkMarketError as exc:
            excluded.append((cid, f"QUOTE_{exc}"))
            continue
        if nq.data_basis != data_basis:
            excluded.append((cid, "QUOTE_DATA_BASIS_MISMATCH"))
            continue
        spreads[cid] = nq.spread_bps
    bench_bars: tuple[StrategyBar, ...] | None = None
    if benchmark is not None and benchmark.data_basis == data_basis:
        try:
            bench_record = registry.get(benchmark.canonical_id)
            bench_bars = normalize_series(benchmark, bench_record, now).bars
        except (UkMarketError, ValueError):
            bench_bars = None  # relative strength / regime become UNAVAILABLE
    report: ScanReport | None = None
    shortlists: dict[str, Shortlist] = {}
    signals: list[ResearchSignal] = []
    decisions: list[Decision] = []
    if normalized:
        report = run_broad_scan(
            sorted(normalized), lambda cid: normalized[cid].bars, cutoff, data_basis=data_basis,
            benchmark=bench_bars, spreads=spreads, calendar=XLON, batch_size=100,
        )
        shortlists = {t: build_shortlist(report, cfg) for t, cfg in UK_SCORING.items()}
        features = {f.canonical_id: f for f in report.features}
        session = XLON.session(cutoff)
        assert session is not None
        cutoff_time = session.close_utc
        for track in ("SWING", "POSITION", "DAY"):
            policy = uk_policy(track, now)
            for cand in shortlists[track].research:
                track_signals: tuple[ResearchSignal, ...] = ()
                if track == "SWING":
                    try:
                        track_signals = daily_signals(
                            cand.canonical_id, normalized[cand.canonical_id].bars, cutoff,
                            cutoff_time=cutoff_time, generated_at=now,
                        )
                    except MethodError as exc:
                        excluded.append((cand.canonical_id, f"METHOD_{exc}"))
                signals.extend(track_signals)
                feat = features[cand.canonical_id]
                market = MarketContext(
                    cand.canonical_id, feat.last_close, cutoff_time, feat.atr14, "UNKNOWN",
                    session_open=XLON.is_open(now), execution_eligible=False,
                )
                decisions.append(decide(
                    track_signals, admissions, policy,
                    PortfolioState((), {track: policy.virtual_capital}), market, now,
                ))
    return UkScanResult(
        cutoff, data_basis, len(members), tuple(identities), tuple(excluded), report,
        shortlists, tuple(signals), tuple(decisions), spreads,
    )
