"""SD-103 integrated SideDeck trading pipeline: one entry point over the existing components.

MARKET DATA -> SCANNER -> STRATEGIES -> AI AGENTS -> DECISION ENGINE -> RISK ENGINE ->
PORTFOLIO ALLOCATION -> PAPER BROKER -> FILLS -> POSITION MANAGEMENT -> EXIT -> PERFORMANCE

Nothing here is new trading logic. Each stage calls the verified module that already owns it:

| Stage | Module |
|---|---|
| data admission | ``m2_market_data.normalize_daily_bars`` + ``us_equity_calendar`` session coverage |
| scanner | ``sd067_market_scanner`` (broad scan + SWING shortlist) |
| strategy research | ``p5_sd021_research.research_payload`` (SD-021 evaluation, surfaces, walk-forward) |
| strategy admission | ``sd022_robustness_audit.audit_report`` + the SD-071 floor (>= 30 locked-OOS trades) |
| native signals | ``sd014_strategy_engine.generate_signals`` -> ``sd070`` ``ResearchSignal`` |
| AI agents | ``sd069_agent_signal_adapters`` (records from authorized runs only) |
| decision + sizing | ``sd071_decision_engine.decide`` |
| risk gate + ledger | ``sd072_track_risk_limits`` via ``sd079_track_ledgers.TrackLedger`` |

Two modes:

* ``run``: the decision at the latest cutoff. Order intents are ``PROPOSED_NOT_SUBMITTED``; a
  historical close is never an executable quote.
* ``replay``: a forward test. Strategy admission is **locked from data before the replay
  window**; then each session the same decision and risk code runs on bars up to that close,
  approved entries fill at the next session's open in the SIMULATED_LOCAL ledger, and stops,
  targets, time exits and strategy exits are managed bar by bar. Results are attributed to
  strategy and version.

Broker routes: only ``SIMULATED_LOCAL`` is available. eToro Demo and Alpaca Paper return
``NOT_RELEASED`` until the SD-063/SD-064 policy-to-transport wiring (SD-074F) is reviewed and
the owner signs a release; eToro Real is permanently excluded. No network, credential or
broker request exists in this module.

A run on a ``SYNTHETIC_FIXTURE`` basis proves plumbing only. A ``REAL_DATA`` replay uses
genuine historical bars with simulated fills: it is research evidence, not broker evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import tempfile
import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

from sidedeck.application.m2_market_data import MarketDataError, normalize_daily_bars
from sidedeck.application.p5_sd021_research import research_payload
from sidedeck.application.sd014_strategy_engine import (
    StrategyBar, StrategySpec, bars_from_normalized, catalogue, generate_signals,
)
from sidedeck.application.sd022_robustness_audit import audit_report
from sidedeck.application.sd067_market_scanner import (
    DEFAULT_SCORING, ScanError, build_shortlist, run_broad_scan,
)
from sidedeck.application.sd069_agent_signal_adapters import (
    PROFILES, AgentOutcome, adapt_agent_record,
)
from sidedeck.application.sd070_research_signal import EvidenceRef, ResearchSignal
from sidedeck.application.sd071_decision_engine import (
    MIN_OOS_TRADES_FLOOR, Decision, Holding, MarketContext, PortfolioState, StrategyAdmission,
    TrackPolicy, decide,
)
from sidedeck.application.sd072_track_risk_limits import TrackLimits
from sidedeck.application.sd079_track_ledgers import LedgerError, Position, TrackLedger
from sidedeck.application.us_equity_calendar import (
    COMPLETE_CALENDAR_YEARS, expected_regular_sessions,
)

SCHEMA = "sidedeck-pipeline-run/1"
TRACK = "SWING"
REAL_DATA, FIXTURE = "REAL_DATA", "SYNTHETIC_FIXTURE"
NY = ZoneInfo("America/New_York")
SIGNAL_STRATEGIES = ("channel_mean_reversion", "liquidity_sweep_reversal", "moving_average_trend")
SIMULATED_LOCAL = "SIMULATED_LOCAL"
BROKER_ROUTES = {
    SIMULATED_LOCAL: "AVAILABLE_LABELLED_SIMULATION",
    "ETORO_DEMO": "NOT_RELEASED: needs SD-074F policy-to-transport wiring, independent review "
                  "and an owner-signed SD-063/SD-064 policy release",
    "ALPACA_PAPER": "NOT_RELEASED: account separation UNVERIFIED and authorization exhausted",
    "ETORO_REAL": "PERMANENTLY_EXCLUDED",
}
STRATEGY_RULES: dict[str, dict[str, str]] = {
    "channel_mean_reversion": {
        "entry": "close <= lowest close + (highest - lowest) x entry_bps / 10000 over the prior "
                 "lookback closes",
        "exit": "close >= channel midpoint, or the ATR stop, or the time exit",
        "target": "CHANNEL_MIDPOINT"},
    "liquidity_sweep_reversal": {
        "entry": "low breaks the prior lookback low, close recovers above it, volume >= "
                 "volume_multiple x lookback average",
        "exit": "next session without the setup, or the ATR stop, or the time exit",
        "target": "RULE_BASED_EXIT_NO_PRICE_TARGET"},
    "moving_average_trend": {
        "entry": "fast SMA of prior closes above slow SMA",
        "exit": "fast SMA at or below slow SMA, or the ATR stop, or the time exit",
        "target": "RULE_BASED_EXIT_NO_PRICE_TARGET"},
}
ZERO = Decimal(0)
CENT = Decimal("0.01")
STALE_FOR_EXECUTION_DAYS = 4


class PipelineError(RuntimeError):
    """A stage refused its input; the run stops or the instrument is excluded."""


class ExecutionNotReleased(PermissionError):
    """A broker route other than the labelled local simulation was requested."""


def require_route(route: str) -> str:
    status = BROKER_ROUTES.get(route)
    if status is None:
        raise ExecutionNotReleased(f"unknown broker route {route!r}")
    if route != SIMULATED_LOCAL:
        raise ExecutionNotReleased(f"{route}: {status}")
    return route


def _sha(value: Any) -> str:
    raw = value if isinstance(value, bytes) else json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def session_close_utc(day: date) -> datetime:
    return datetime.combine(day, time(16, 0), NY).astimezone(UTC)


def session_open_utc(day: date) -> datetime:
    return datetime.combine(day, time(9, 30), NY).astimezone(UTC)


# ---- configuration -------------------------------------------------------------------------

@dataclass(frozen=True)
class PipelineConfig:
    """Research/simulation limits. These are not an allocation of real or Demo capital."""

    virtual_capital: Decimal = Decimal("1000")
    max_position_pct: Decimal = Decimal("0.05")          # USD 50 of 1000
    max_positions: int = 5
    max_gross_exposure_pct: Decimal = Decimal("0.5")
    max_instrument_total_pct: Decimal = Decimal("0.05")
    max_sector_pct: Decimal = Decimal("0.5")
    max_correlation: Decimal = Decimal("0.85")
    risk_per_trade_pct: Decimal = Decimal("0.005")
    stop_atr_multiple: Decimal = Decimal("2")
    min_notional: Decimal = Decimal("10")
    max_signal_age: timedelta = timedelta(days=1)
    max_signal_data_age: timedelta = timedelta(days=4)
    max_price_age: timedelta = timedelta(days=4)
    max_drawdown_pct: Decimal = Decimal("0.10")
    max_daily_loss_pct: Decimal = Decimal("0.03")
    max_entries_per_day: int = 2
    fee_bps: Decimal = Decimal("5")
    slippage_bps: Decimal = Decimal("5")
    limit_premium: Decimal = Decimal("0.005")
    correlation_window: int = 60
    sectors: Mapping[str, str] = field(default_factory=lambda: {
        "US:SPY": "BROAD_MARKET_ETF", "US:QQQ": "BROAD_MARKET_ETF", "US:MSFT": "TECHNOLOGY",
        "US:AAPL": "TECHNOLOGY", "US:SOFI": "FINANCIALS"})
    broker_mappings: Mapping[str, str] = field(default_factory=dict)  # cid -> mapping evidence
    route: str = SIMULATED_LOCAL

    def policy(self, now: datetime, strategies: Iterable[tuple[str, str]],
               instruments: Iterable[str]) -> TrackPolicy:
        return TrackPolicy(
            policy_id="sd103-research-simulation", track=TRACK,
            virtual_capital=self.virtual_capital, max_position_pct=self.max_position_pct,
            max_positions=self.max_positions, max_gross_exposure_pct=self.max_gross_exposure_pct,
            max_instrument_total_pct=self.max_instrument_total_pct,
            max_sector_pct=self.max_sector_pct, max_correlation=self.max_correlation,
            risk_per_trade_pct=self.risk_per_trade_pct, stop_atr_multiple=self.stop_atr_multiple,
            min_notional=self.min_notional, max_signal_age=self.max_signal_age,
            max_signal_data_age=self.max_signal_data_age, max_price_age=self.max_price_age,
            expires_at=now + timedelta(days=1), allowed_strategies=frozenset(strategies),
            allowed_instruments=frozenset(instruments))

    def limits(self) -> TrackLimits:
        return TrackLimits(TRACK, self.max_drawdown_pct, self.max_daily_loss_pct,
                           self.max_entries_per_day)

    def with_costs(self, notional: Decimal) -> Decimal:
        return (notional * (1 + (self.fee_bps + self.slippage_bps) / Decimal(10000))).quantize(
            CENT, rounding=ROUND_HALF_UP)


# ---- stage A: market data ----------------------------------------------------------------------

@dataclass(frozen=True)
class MarketEvidence:
    canonical_id: str
    ticker: str
    basis: str
    source: str
    source_sha256: str
    payload: dict[str, Any]
    bars: tuple[StrategyBar, ...]
    data_cutoff: datetime
    limitations: tuple[str, ...]

    @property
    def last_session(self) -> date:
        return self.bars[-1].day


def admit_market_data(payload: Mapping[str, Any], *, basis: str, through: date,
                      source_sha256: str) -> MarketEvidence:
    """Validated daily bars at or before ``through``; one data basis per run."""
    if basis == REAL_DATA:
        if (payload.get("synthetic_fixture") or payload.get("admission_status")
                != "ADMITTED_RESEARCH_ONLY" or not str(payload.get("source", "")).startswith(
                    "https://")):
            raise PipelineError("REAL_DATA requires an admitted, sourced, non-fixture bundle")
    elif basis == FIXTURE:
        if payload.get("synthetic_fixture") is not True:
            raise PipelineError("a fixture run accepts only bundles labelled synthetic_fixture")
    else:
        raise PipelineError("unknown data basis")
    records = [r for r in payload.get("records", []) if isinstance(r, dict)
               and str(r.get("timestamp", ""))[:10] <= through.isoformat()]
    if not records:
        raise PipelineError("no bars at or before the cutoff")
    truncated = {**payload, "records": records}
    try:
        normalized, _report = normalize_daily_bars(truncated,
                                                   cutoff=session_close_utc(through))
        bars = bars_from_normalized(normalized)
    except (MarketDataError, ValueError) as exc:
        raise PipelineError(f"market data refused: {exc}") from None
    if bars[-1].day.year not in COMPLETE_CALENDAR_YEARS:
        raise PipelineError("bars fall outside the verified session calendar")
    first = max(bars[0].day, date(min(COMPLETE_CALENDAR_YEARS), 1, 1))
    expected = set(expected_regular_sessions(first, bars[-1].day))
    observed = {b.day for b in bars if b.day >= first}
    if expected - observed:
        raise PipelineError(f"missing {len(expected - observed)} regular sessions")
    if observed - expected:
        raise PipelineError("bars on non-session dates")
    limitations = ["DAILY_BARS_ONLY", "HISTORICAL_CLOSE_IS_NOT_AN_EXECUTABLE_QUOTE"]
    if payload.get("corporate_actions_verified") is not True:
        limitations.append("CORPORATE_ACTIONS_NOT_INDEPENDENTLY_VERIFIED")
    if payload.get("adjustment") == "split_adjusted":
        limitations.append("SPLIT_ADJUSTED_PRICE_ONLY_NO_DIVIDENDS")
    if basis == FIXTURE:
        limitations.append("SYNTHETIC_FIXTURE_NOT_MARKET_EVIDENCE")
    return MarketEvidence(str(payload["instrument_id"]), str(payload["ticker"]), basis,
                          str(payload["source"]), source_sha256, truncated, bars,
                          session_close_utc(bars[-1].day), tuple(limitations))


def load_bundle(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def atr14(bars: Sequence[StrategyBar]) -> Decimal:
    window = bars[-15:]
    ranges = [max(b.high - b.low, abs(b.high - p.close), abs(b.low - p.close))
              for p, b in zip(window, window[1:])]
    if not ranges:
        raise PipelineError("ATR needs at least two bars")
    return sum(ranges, ZERO) / Decimal(len(ranges))


def correlation(a: Sequence[StrategyBar], b: Sequence[StrategyBar], window: int) -> Decimal:
    days = sorted({x.day for x in a} & {y.day for y in b})[-(window + 1):]
    if len(days) < 20:
        raise PipelineError("not enough overlapping sessions for a correlation")
    ca = {x.day: x.close for x in a}
    cb = {y.day: y.close for y in b}
    ra = [float(ca[d] / ca[p] - 1) for p, d in zip(days, days[1:])]
    rb = [float(cb[d] / cb[p] - 1) for p, d in zip(days, days[1:])]
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va = sum((x - ma) ** 2 for x in ra)
    vb = sum((y - mb) ** 2 for y in rb)
    if va == 0 or vb == 0:
        raise PipelineError("zero-variance series")
    return Decimal(str(round(cov / math.sqrt(va * vb), 6)))


# ---- stage B: strategies and admission -----------------------------------------------------------

@dataclass(frozen=True)
class StrategyResearch:
    canonical_id: str
    records: tuple[dict[str, Any], ...]
    admissions: tuple[StrategyAdmission, ...]
    research_sha256: str
    benchmark: dict[str, Any]


def _spec(strategy_id: str) -> StrategySpec:
    return next(s for s in catalogue() if s.strategy_id == strategy_id)


def research_strategies(evidence: MarketEvidence, cfg: PipelineConfig) -> StrategyResearch:
    """SD-021 evaluation + SD-022 audit + SD-071 floor, per instrument. Never relaxed."""
    report = research_payload(evidence.payload,
                              cutoff=session_close_utc(evidence.last_session))
    research_sha = _sha(report)
    audit = audit_report(report)
    records: list[dict[str, Any]] = []
    admissions: list[StrategyAdmission] = []
    for strategy_id in SIGNAL_STRATEGIES:
        spec = _spec(strategy_id)
        audited = audit["strategies"][strategy_id]
        m = audited["metrics"]
        reasons = list(audited["reasons"])
        if m["oos_trades"] < MIN_OOS_TRADES_FLOOR:
            reasons.append(f"OOS_TRADES_{m['oos_trades']}_BELOW_SD071_FLOOR_{MIN_OOS_TRADES_FLOOR}")
        if audited["audited_status"] == "REJECTED":
            status = "REJECTED"
        elif audited["audited_status"] == "VERIFIED" and not reasons and audited["locked_oos"]:
            status = "ADMITTED"
        else:
            status = "RESEARCH_ONLY"
        admissions.append(StrategyAdmission(
            strategy_id, spec.version, TRACK, status, f"sd103-research:{research_sha}",
            int(m["oos_trades"]), bool(audited["locked_oos"]) and m["oos_observations"] > 0))
        rules = STRATEGY_RULES[strategy_id]
        records.append({
            "strategy_id": strategy_id, "version": spec.version,
            "parameters": dict(spec.parameters), "instrument": evidence.canonical_id,
            "markets": ["XNYS"], "track": TRACK, "entry": rules["entry"], "exit": rules["exit"],
            "stop_loss": f"entry - {cfg.stop_atr_multiple} x ATR14 (SD-071 sizing)",
            "target": rules["target"],
            "holding_period_sessions": [spec.holding_period_min, spec.holding_period_max],
            "position_sizing": (f"risk {cfg.risk_per_trade_pct} of track capital / stop "
                                f"distance, capped at {cfg.max_position_pct} of capital"),
            "max_risk_per_trade_usd": str(cfg.virtual_capital * cfg.risk_per_trade_pct),
            "historical": {k: m[k] for k in ("observations", "completed_trade_count",
                                             "profit_factor", "max_drawdown",
                                             "annualized_return", "win_rate", "sharpe",
                                             "exposure")},
            "out_of_sample": {k: m[k] for k in ("oos_observations", "oos_trades",
                                                "oos_profit_factor", "oos_ending_equity",
                                                "oos_max_drawdown")},
            "parameter_stability": audited["parameter_stability"],
            "walk_forward_windows": audited["walk_forward_windows"],
            "selection_basis": audited["selection_basis"],
            "evidence": {"bundle_sha256": evidence.source_sha256, "research_sha256": research_sha,
                         "cost_bps": m["fee_slippage_bps"], "data_basis": evidence.basis,
                         "admission_data_through": evidence.last_session.isoformat()},
            "admission": status, "admission_reasons": reasons})
    bench = audit["strategies"].get("buy_and_hold")
    benchmark = {} if bench is None else {
        "ending_equity": bench["metrics"]["ending_equity"],
        "basis": "PRICE_ONLY_BUY_AND_HOLD_EXCLUDES_DIVIDENDS"}
    return StrategyResearch(evidence.canonical_id, tuple(records), tuple(admissions),
                            research_sha, benchmark)


# ---- stage C: signals ------------------------------------------------------------------------

@dataclass(frozen=True)
class StrategyState:
    strategy_id: str
    version: str
    state: str          # ENTRY | EXIT | HOLDING | FLAT
    day: date


def strategy_states(bars: Sequence[StrategyBar],
                    signal_maps: Mapping[str, Mapping[date, str]] | None = None
                    ) -> tuple[StrategyState, ...]:
    """State of every strategy at the last bar. ``generate_signals`` is causal, so a map
    computed once on a longer series gives the same answer for any earlier day (tested)."""
    last = bars[-1].day
    states = []
    for strategy_id in SIGNAL_STRATEGIES:
        spec = _spec(strategy_id)
        signals = (signal_maps or {}).get(strategy_id) or generate_signals(spec, bars)
        today = signals.get(last, "HOLD")
        if today == "BUY":
            state = "ENTRY"
        elif today == "SELL":
            state = "EXIT"
        else:
            prior = [signals[b.day] for b in bars if signals.get(b.day) in ("BUY", "SELL")]
            state = "HOLDING" if prior and prior[-1] == "BUY" else "FLAT"
        states.append(StrategyState(strategy_id, spec.version, state, last))
    return tuple(states)


def native_signals(evidence: MarketEvidence, states: Sequence[StrategyState],
                   research: StrategyResearch, now: datetime) -> tuple[ResearchSignal, ...]:
    out = []
    for st in states:
        if st.state != "ENTRY":
            continue
        spec = _spec(st.strategy_id)
        out.append(ResearchSignal(
            canonical_id=evidence.canonical_id, track=TRACK, source_kind="NATIVE_STRATEGY",
            source_id=st.strategy_id, source_version=st.version,
            horizon_min_days=spec.holding_period_min, horizon_max_days=spec.holding_period_max,
            direction="LONG",
            evidence=(EvidenceRef("strategy_research", f"{evidence.canonical_id}:"
                                  f"{st.strategy_id}", research.research_sha256),
                      EvidenceRef("market_bundle", evidence.canonical_id,
                                  evidence.source_sha256)),
            generated_at=now, data_cutoff=evidence.data_cutoff,
            invalidation=("close at or below the ATR stop", "the strategy exit rule fires"),
            rationale=STRATEGY_RULES[st.strategy_id]["entry"]))
    return tuple(out)


def channel_target(bars: Sequence[StrategyBar], spec: StrategySpec) -> Decimal | None:
    if spec.strategy_id != "channel_mean_reversion":
        return None
    lookback = int(dict(spec.parameters).get("lookback", "20"))
    window = [b.close for b in bars[-(lookback + 1):-1]]
    if len(window) < lookback:
        return None
    return ((min(window) + max(window)) / 2).quantize(CENT, rounding=ROUND_HALF_UP)


def agent_outcomes(records: Sequence[Mapping[str, Any]], shortlist: Iterable[str],
                   now: datetime) -> tuple[AgentOutcome, ...]:
    """Records come only from separately authorized agent runs. Missing -> UNAVAILABLE."""
    allowed = tuple(shortlist)
    outcomes: list[AgentOutcome] = []
    seen = set()
    for record in records:
        invoked = str(record.get("portfolio", ""))
        if invoked not in PROFILES:
            continue
        seen.add(invoked)
        outcomes.append(adapt_agent_record(record, invoked=invoked, allowed_ids=allowed, now=now))
    for name in sorted(set(PROFILES) - seen):
        reason = "NO_AUTHORIZED_AGENT_RUN: provider spend and scope approval required"
        outcomes.append(AgentOutcome(name, None, "UNAVAILABLE", reason, None, _sha(reason)))
    return tuple(outcomes)


# ---- stage D/E: decision, risk and order intent ---------------------------------------------------

def _direction(decision: Decision, held: bool, exit_signal: bool) -> str:
    if held and exit_signal:
        return "SELL"
    if decision.status == "ELIGIBLE":
        return "BUY"
    if held:
        return "HOLD"
    return "ABSTAIN"


def decision_row(decision: Decision, *, evidence: MarketEvidence,
                 signals: Sequence[ResearchSignal], cfg: PipelineConfig, held: bool,
                 exit_signal: bool, atr: Decimal) -> dict[str, Any]:
    by_id = {s.signal_id: s for s in signals}
    qualified = [by_id[i] for i in decision.qualified_signal_ids if i in by_id]
    natives = [s for s in signals if s.source_kind == "NATIVE_STRATEGY"]
    strategies = [f"{s.source_id}@{s.source_version}" for s in (qualified or natives)]
    entry = evidence.bars[-1].close
    sizing = decision.sizing
    stop = sizing.stop_price if sizing else (entry - atr * cfg.stop_atr_multiple).quantize(CENT)
    target = next((t for s in (qualified or natives)
                   if (t := channel_target(evidence.bars, _spec(s.source_id))) is not None), None)
    risk_reward = None
    if target is not None and entry > stop and target > entry:
        risk_reward = str(((target - entry) / (entry - stop)).quantize(Decimal("0.01")))
    return {
        "symbol": evidence.canonical_id, "ticker": evidence.ticker,
        "direction": _direction(decision, held, exit_signal), "strategy": strategies,
        "entry": {"reference_close": str(entry),
                  "reference_basis": "HISTORICAL_CLOSE_NOT_EXECUTABLE",
                  "executable_rule": f"LIMIT_IOC <= fresh broker ask x {1 + cfg.limit_premium}"},
        "stop_loss": str(stop), "target": None if target is None else str(target),
        "target_rule": None if target is not None else "RULE_BASED_EXIT",
        "holding_period": None if sizing is None else f"<= {sizing.horizon_max_days} sessions",
        "quantity": None if sizing is None else str(sizing.quantity),
        "capital_required_usd": None if sizing is None else str(cfg.with_costs(sizing.notional)),
        "risk_reward": risk_reward,
        "evidence": {"bundle_sha256": evidence.source_sha256, "data_basis": evidence.basis,
                     "data_cutoff": evidence.data_cutoff.isoformat(),
                     "qualified_signals": list(decision.qualified_signal_ids),
                     "supporting_signals": list(decision.supporting_signal_ids),
                     "disagreements": list(decision.disagreements)},
        "decision": decision.status, "reasons": list(decision.reasons),
        "execution_permission": decision.execution_permission}


def order_intent(decision: Decision, *, evidence: MarketEvidence, cfg: PipelineConfig,
                 strategy: str, run_key: str) -> dict[str, Any]:
    if decision.sizing is None:
        raise PipelineError("only ELIGIBLE decisions produce order intents")
    reference = evidence.bars[-1].close
    limit = (reference * (1 + cfg.limit_premium)).quantize(CENT, rounding=ROUND_DOWN)
    intent_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"sidedeck:sd103:{run_key}:"
                               f"{evidence.canonical_id}:{strategy}"))
    return {"intent_id": intent_id, "canonical_id": evidence.canonical_id, "side": "BUY",
            "units": str(decision.sizing.quantity), "order_type": "LIMIT_IOC",
            "limit_price": str(limit), "limit_basis": "SIMULATION: reference close x (1 + "
            f"{cfg.limit_premium}); a broker order re-prices from a fresh executable ask",
            "stop_price": str(decision.sizing.stop_price), "strategy": strategy,
            "decision_policy": decision.policy_id,
            "qualified_signals": list(decision.qualified_signal_ids),
            "broker_route": cfg.route, "broker_route_status": BROKER_ROUTES[cfg.route],
            "broker_mapping": cfg.broker_mappings.get(evidence.canonical_id, "UNMAPPED"),
            "status": "PROPOSED_NOT_SUBMITTED"}


def portfolio_state(ledger: TrackLedger, cfg: PipelineConfig) -> PortfolioState:
    holdings = tuple(Holding(p.canonical_id, TRACK, (p.quantity * p.entry_price).quantize(CENT),
                             cfg.sectors.get(p.canonical_id, "UNKNOWN"))
                     for p in ledger.positions.values())
    return PortfolioState(holdings, {TRACK: ledger.cash})


@dataclass
class StageContext:
    """Inputs shared by every decision pass of one run."""

    cfg: PipelineConfig
    evidence: dict[str, MarketEvidence]
    research: dict[str, StrategyResearch]
    agent_records: tuple[Mapping[str, Any], ...] = ()
    signal_maps: dict[str, dict[str, dict[date, str]]] = field(default_factory=dict)


def _scan(views: Mapping[str, MarketEvidence]) -> tuple[list[str], dict[str, Any]]:
    basis = next(iter(views.values())).basis
    try:
        report = run_broad_scan(sorted(views), lambda cid: views[cid].bars,
                                max(v.last_session for v in views.values()), data_basis=basis,
                                benchmark=views["US:SPY"].bars if "US:SPY" in views else None)
        swing = build_shortlist(report, DEFAULT_SCORING[TRACK])
    except ScanError as exc:
        return sorted(views), {"status": "SCAN_REFUSED", "reason": str(exc)}
    return [c.canonical_id for c in swing.research], {
        "status": "COMPLETED", "data_basis": basis, "scanned": len(report.features),
        "excluded": [list(e) for e in report.excluded],
        "shortlist": [{"canonical_id": c.canonical_id, "rank": c.rank, "score": str(c.score)}
                      for c in swing.research],
        "filtered": [list(f) for f in swing.filtered], "note": swing.note}


def decision_pass(ctx: StageContext, *, through: date, now: datetime, ledger: TrackLedger,
                  run_key: str, scan: bool = True) -> dict[str, Any]:
    cfg = ctx.cfg
    views = {cid: replace(ev, bars=tuple(b for b in ev.bars if b.day <= through))
             for cid, ev in ctx.evidence.items()}
    views = {cid: replace(v, data_cutoff=session_close_utc(v.bars[-1].day))
             for cid, v in views.items() if len(v.bars) >= 30}
    out: dict[str, Any] = {"cutoff_session": through.isoformat(), "scanner": None,
                           "agents": [], "decisions": [], "risk": [], "orders": [],
                           "exit_signals": []}
    if not views:
        out["no_trade"] = "NO TRADE: no admissible market data at this cutoff"
        return out
    shortlist = sorted(views)
    if scan:
        shortlist, out["scanner"] = _scan(views)
    outcomes = agent_outcomes(ctx.agent_records, shortlist, now)
    out["agents"] = [{"portfolio": o.portfolio, "instrument": o.canonical_id,
                      "status": o.status, "reason": o.reason,
                      "direction": o.signal.direction if o.signal else None,
                      "model": o.signal.source_version if o.signal else None,
                      "output_sha256": o.output_sha256} for o in outcomes]
    agent_signals = [o.signal for o in outcomes if o.signal is not None]
    admitted = {(a.strategy_id, a.version) for r in ctx.research.values() for a in r.admissions
                if a.status == "ADMITTED"}
    policy = cfg.policy(now, admitted, views)
    held = {p.canonical_id for p in ledger.positions.values()}
    for cid in sorted(views):
        ev, research = views[cid], ctx.research.get(cid)
        if research is None:
            continue
        states = strategy_states(ev.bars, ctx.signal_maps.get(cid))
        exiting = [s.strategy_id for s in states if s.state == "EXIT"]
        if cid in held and exiting:
            out["exit_signals"].append({"canonical_id": cid, "strategies": exiting})
        signals = list(native_signals(ev, states, research, now))
        signals += [s for s in agent_signals if s.canonical_id == cid]
        correlations: dict[str, Decimal] = {}
        for other in held - {cid}:
            if other in views:
                try:
                    correlations[other] = correlation(ev.bars, views[other].bars,
                                                      cfg.correlation_window)
                except PipelineError:
                    pass                       # missing evidence fails closed in decide()
        atr = atr14(ev.bars)
        market = MarketContext(cid, ev.bars[-1].close, ev.data_cutoff, atr,
                               cfg.sectors.get(cid, "UNKNOWN"), session_open=False,
                               execution_eligible=cid in cfg.broker_mappings,
                               correlations=correlations)
        decision = decide(signals, research.admissions, policy, portfolio_state(ledger, cfg),
                          market, now)
        out["decisions"].append(decision_row(decision, evidence=ev, signals=signals, cfg=cfg,
                                             held=cid in held, exit_signal=bool(exiting),
                                             atr=atr))
        if decision.status != "ELIGIBLE" or decision.sizing is None:
            continue
        prices = {p.canonical_id: views[p.canonical_id].bars[-1].close
                  for p in ledger.positions.values() if p.canonical_id in views}
        reasons: list[str] = []
        if len(prices) != len(ledger.positions):
            reasons.append("MISSING_MARK_PRICE_FOR_OPEN_POSITION")
            gate_info = {"drawdown_pct": "UNAVAILABLE", "daily_loss_pct": "UNAVAILABLE"}
        else:
            gate = ledger.risk_gate(cfg.limits(), prices, ledger.equity(prices),
                                    through.isoformat())
            reasons += list(gate.reasons)
            gate_info = {"drawdown_pct": str(gate.drawdown_pct),
                         "daily_loss_pct": str(gate.daily_loss_pct)}
        required = cfg.with_costs(decision.sizing.notional)
        if required > ledger.cash:
            reasons.append("INSUFFICIENT_CASH_INCLUDING_COSTS")
        risk = {"canonical_id": cid, "decision": "APPROVED" if not reasons else "REJECTED",
                "reasons": reasons, **gate_info, "capital_required_usd": str(required)}
        out["risk"].append(risk)
        if risk["decision"] == "APPROVED":
            by_id = {s.signal_id: s for s in signals}
            strategy = next(f"{by_id[i].source_id}@{by_id[i].source_version}"
                            for i in decision.qualified_signal_ids if i in by_id)
            intent = order_intent(decision, evidence=ev, cfg=cfg, strategy=strategy,
                                  run_key=run_key)
            intent["_decision"] = decision
            out["orders"].append(intent)
    out["no_trade"] = None if out["orders"] else no_trade_explanation(out, ctx)
    return out


def no_trade_explanation(out: Mapping[str, Any], ctx: StageContext) -> str:
    admitted = [a for r in ctx.research.values() for a in r.admissions if a.status == "ADMITTED"]
    if not admitted:
        return ("NO TRADE: no strategy is ADMITTED (each needs SD-022 robustness VERIFIED and "
                f">= {MIN_OOS_TRADES_FLOOR} locked out-of-sample trades); signals can reach "
                "WATCHLIST only. No opportunity is manufactured.")
    statuses = sorted({d["decision"] + ":" + ",".join(d["reasons"][:1])
                       for d in out["decisions"]})
    return "NO TRADE: no admitted strategy produced an approved entry (" + "; ".join(
        statuses) + ")."


# ---- paper broker (labelled simulation) and replay ---------------------------------------------

class BrokerOutage(RuntimeError):
    pass


@dataclass
class SimulatedBroker:
    """Fills at the next session open with slippage and fees. Every fill is SIMULATED_LOCAL.
    Fault injection covers outage, partial and unexpected over-fill scenarios."""

    fee_bps: Decimal
    slippage_bps: Decimal
    outage_days: frozenset[date] = frozenset()
    partial_ratio: Decimal = Decimal(1)
    overfill: bool = False
    submitted: set[str] = field(default_factory=set)

    def fee(self, units: Decimal, price: Decimal) -> Decimal:
        return (units * price * self.fee_bps / Decimal(10000)).quantize(CENT, ROUND_HALF_UP)

    def entry(self, intent: Mapping[str, Any], bar: StrategyBar) -> dict[str, Any]:
        if intent["intent_id"] in self.submitted:
            raise PipelineError("duplicate submission refused (idempotency key reused)")
        self.submitted.add(intent["intent_id"])
        if bar.day in self.outage_days:
            raise BrokerOutage("simulated broker outage: outcome unknown")
        price = (bar.open * (1 + self.slippage_bps / Decimal(10000))).quantize(CENT,
                                                                                ROUND_HALF_UP)
        units = Decimal(intent["units"])
        if price > Decimal(intent["limit_price"]):
            return {"status": "EXPIRED_IOC_LIMIT", "units": "0", "basis": SIMULATED_LOCAL}
        filled = units * Decimal("1.5") if self.overfill else (units * self.partial_ratio
                                                               ).quantize(Decimal("0.0001"),
                                                                          rounding=ROUND_DOWN)
        status = ("FILLED" if filled == units else "PARTIALLY_FILLED" if filled < units
                  else "OVERFILLED")
        return {"status": status, "units": str(filled), "price": str(price),
                "fee": str(self.fee(filled, price)), "basis": SIMULATED_LOCAL,
                "at": session_open_utc(bar.day).isoformat()}

    def exit_price(self, raw: Decimal) -> Decimal:
        return (raw * (1 - self.slippage_bps / Decimal(10000))).quantize(CENT, ROUND_HALF_UP)


def manage_position(position: Position, bar: StrategyBar, *, sessions_held: int,
                    horizon: int, target: Decimal | None) -> tuple[str, Decimal] | None:
    """Exit check on one daily bar. If stop and target are both touched, the stop wins
    (conservative); a gap through the stop fills at the open, never at the stop. With daily
    bars this is a monitoring rule, not a guaranteed resting stop order."""
    if bar.low <= position.stop_price:
        return "STOP_LOSS", min(bar.open, position.stop_price)
    if target is not None and bar.high >= target:
        return "TARGET", max(bar.open, target)
    if sessions_held >= horizon:
        return "TIME_EXIT", bar.close
    return None


def replay(ctx: StageContext, *, start: date, end: date, workdir: Path,
           broker: SimulatedBroker | None = None) -> dict[str, Any]:
    cfg = ctx.cfg
    require_route(cfg.route)
    workdir.mkdir(parents=True, exist_ok=True)
    bases = {ev.basis for ev in ctx.evidence.values()}
    if len(bases) != 1:
        raise PipelineError("one data basis per run (fixtures never mix with real data)")
    marker = workdir / "basis.json"
    meta = {"basis": next(iter(bases)), "capital": str(cfg.virtual_capital)}
    if marker.exists() and json.loads(marker.read_text(encoding="utf-8")) != meta:
        raise PipelineError("workdir belongs to a different basis or capital (no account mixing)")
    marker.write_text(json.dumps(meta), encoding="utf-8")
    ledger = TrackLedger.open(workdir / "swing-ledger.sqlite3", TRACK, cfg.virtual_capital)
    broker = broker or SimulatedBroker(cfg.fee_bps, cfg.slippage_bps)
    for cid, ev in ctx.evidence.items():
        ctx.signal_maps.setdefault(cid, {s: generate_signals(_spec(s), ev.bars)
                                         for s in SIGNAL_STRATEGIES})
    sessions = expected_regular_sessions(start, end)
    by_day = {cid: {b.day: b for b in ev.bars} for cid, ev in ctx.evidence.items()}
    pending: list[dict[str, Any]] = []
    pending_exits: set[str] = set()
    attribution: dict[str, dict[str, Any]] = {}
    events: list[dict[str, Any]] = []
    marks: list[tuple[str, str]] = []
    halted: str | None = None
    previous_equity = cfg.virtual_capital
    for day in sessions:
        bars_today = {cid: b[day] for cid, b in by_day.items() if day in b}
        # 1. fills at the open, for orders decided at the previous close
        for intent in pending:
            cid = intent["canonical_id"]
            bar = bars_today.get(cid)
            decision: Decision = intent["_decision"]
            record = {k: v for k, v in intent.items() if k != "_decision"}
            if bar is None:
                events.append({**record, "event": "ORDER_EXPIRED_NO_SESSION", "day": str(day)})
                continue
            try:
                fill = broker.entry(intent, bar)
            except BrokerOutage as exc:
                halted = f"UNRESOLVED_ORDER {intent['intent_id']}: {exc}"
                events.append({**record, "event": "UNRESOLVED", "day": str(day),
                               "reason": str(exc)})
                continue
            if fill["status"] == "OVERFILLED":
                halted = f"UNRESOLVED_ORDER {intent['intent_id']}: fill exceeds the order"
                events.append({**record, "event": "UNRESOLVED", "day": str(day),
                               "reason": "broker reported more units than ordered"})
                continue
            if fill["status"] == "EXPIRED_IOC_LIMIT":
                events.append({**record, "event": "EXPIRED_IOC_LIMIT", "day": str(day)})
                continue
            filled = Decimal(fill["units"])
            if decision.sizing is None:
                raise PipelineError("order intent lost its sizing")
            sized = replace(decision, sizing=replace(decision.sizing, quantity=filled))
            try:
                ledger.open_from_decision(intent["intent_id"], sized, Decimal(fill["price"]),
                                          Decimal(fill["fee"]),
                                          datetime.fromisoformat(fill["at"]),
                                          limits=cfg.limits(), prices={
                                              p.canonical_id: by_day[p.canonical_id][
                                                  max(d for d in by_day[p.canonical_id]
                                                      if d < day)].close
                                              for p in ledger.positions.values()},
                                          session_start_equity=previous_equity)
            except LedgerError as exc:
                events.append({**record, "event": "REJECTED_BY_LEDGER", "day": str(day),
                               "reason": str(exc)})
                continue
            spec = _spec(intent["strategy"].split("@")[0])
            attribution[intent["intent_id"]] = {
                "strategy": intent["strategy"], "canonical_id": cid, "opened": str(day),
                "units_ordered": intent["units"], "units_filled": str(filled),
                "fill_status": fill["status"], "entry_price": fill["price"],
                "entry_fee": fill["fee"], "stop": intent["stop_price"],
                "target": intent.get("target"), "horizon": spec.holding_period_max,
                "sessions_held": 0, "basis": SIMULATED_LOCAL}
            events.append({**record, "event": fill["status"], "day": str(day), "fill": fill})
        pending = []
        # 2. position management on today's bar
        for ref, position in list(ledger.positions.items()):
            bar = bars_today.get(position.canonical_id)
            if bar is None:
                continue
            info = attribution[ref]
            outcome: tuple[str, Decimal] | None
            if ref in pending_exits:
                outcome = ("STRATEGY_EXIT", bar.open)
            else:
                outcome = manage_position(position, bar, sessions_held=info["sessions_held"],
                                          horizon=info["horizon"],
                                          target=None if info["target"] is None
                                          else Decimal(info["target"]))
            info["sessions_held"] += 1
            if outcome is None:
                continue
            reason, raw = outcome
            price = broker.exit_price(raw)
            fee = broker.fee(position.quantity, price)
            at = (session_close_utc(day) if reason == "TIME_EXIT"
                  else session_open_utc(day) + timedelta(minutes=1))
            pnl = ledger.close(ref, price, fee, at, reason)
            info.update({"closed": str(day), "exit_reason": reason, "exit_price": str(price),
                         "exit_fee": str(fee), "realized_pnl": str(pnl)})
            events.append({"event": "CLOSED", "intent_id": ref, "day": str(day),
                           "reason": reason, "price": str(price), "pnl": str(pnl),
                           "basis": SIMULATED_LOCAL})
        pending_exits = set()
        # 3. decisions at the close, on bars up to and including today only
        if halted is None:
            now = session_close_utc(day) + timedelta(minutes=5)
            result = decision_pass(ctx, through=day, now=now, ledger=ledger,
                                   run_key=day.isoformat(), scan=False)
            for intent in result["orders"]:
                cid = intent["canonical_id"]
                spec = _spec(intent["strategy"].split("@")[0])
                target = channel_target(tuple(b for b in ctx.evidence[cid].bars if b.day <= day),
                                        spec)
                intent["target"] = None if target is None else str(target)
                pending.append(intent)
            events.extend({"event": "DECISION", "day": str(day),
                           **{k: d[k] for k in ("symbol", "decision", "direction", "strategy",
                                                "reasons")}}
                          for d in result["decisions"] if d["decision"] != "ABSTAIN")
            held_refs = {p.canonical_id: r for r, p in ledger.positions.items()}
            for item in result["exit_signals"]:
                held_ref = held_refs.get(item["canonical_id"])
                strategy = attribution.get(held_ref or "", {}).get("strategy", "").split("@")[0]
                if held_ref and strategy in item["strategies"]:
                    pending_exits.add(held_ref)
        prices = {p.canonical_id: bars_today[p.canonical_id].close
                  for p in ledger.positions.values() if p.canonical_id in bars_today}
        if len(prices) == len(ledger.positions):
            previous_equity = ledger.mark(prices, session_close_utc(day))
            marks.append((day.isoformat(), str(previous_equity)))
    return {"ledger": ledger, "events": events, "attribution": attribution, "marks": marks,
            "halted": halted, "sessions": len(sessions)}


# ---- performance and reconciliation --------------------------------------------------------------

def performance(result: Mapping[str, Any], ctx: StageContext, *, start: date,
                end: date) -> dict[str, Any]:
    cfg = ctx.cfg
    ledger: TrackLedger = result["ledger"]
    closed = [a for a in result["attribution"].values() if "realized_pnl" in a]
    by_strategy: dict[str, list[Decimal]] = {}
    for item in closed:
        by_strategy.setdefault(item["strategy"], []).append(Decimal(item["realized_pnl"]))
    strategies = {}
    for name, pnls in sorted(by_strategy.items()):
        gains = sum((p for p in pnls if p > 0), ZERO)
        losses = sum((-p for p in pnls if p < 0), ZERO)
        wins = sum(1 for p in pnls if p > 0)
        verdict = ("INSUFFICIENT_FORWARD_TRADES" if len(pnls) < 10 else
                   "RETIRE_CANDIDATE" if losses and gains / losses < 1 else "CONTINUE_TESTING")
        strategies[name] = {
            "closed_trades": len(pnls), "wins": wins,
            "win_rate": str((Decimal(wins) / Decimal(len(pnls))).quantize(Decimal("0.001"))),
            "profit_factor": ("UNDEFINED" if losses == 0
                              else str((gains / losses).quantize(Decimal("0.001")))),
            "net_pnl_usd": str(sum(pnls, ZERO)), "verdict": verdict}
    equities = [Decimal(e) for _, e in result["marks"]] or [cfg.virtual_capital]
    peak, max_dd = cfg.virtual_capital, ZERO
    for value in equities:
        peak = max(peak, value)
        max_dd = max(max_dd, (peak - value) / peak)
    bench = []
    for ev in ctx.evidence.values():
        window = [b for b in ev.bars if start <= b.day <= end]
        if len(window) >= 2:
            bench.append(window[-1].close / window[0].close)
    open_cost = sum((p.quantity * p.entry_price + p.entry_fee
                     for p in ledger.positions.values()), ZERO)
    expected_cash = cfg.virtual_capital + ledger.realized_pnl - open_cost
    fixture = any(ev.basis == FIXTURE for ev in ctx.evidence.values())
    return {
        "basis": ("SIMULATION_ON_SYNTHETIC_FIXTURE_NOT_PERFORMANCE_EVIDENCE" if fixture
                  else "FORWARD_REPLAY_ON_GENUINE_HISTORY_WITH_SIMULATED_FILLS"),
        "window": [start.isoformat(), end.isoformat()], "sessions": result["sessions"],
        "starting_equity": str(cfg.virtual_capital), "ending_equity": str(equities[-1]),
        "total_return": str((equities[-1] / cfg.virtual_capital - 1).quantize(Decimal("0.0001"))),
        "max_drawdown": str(max_dd.quantize(Decimal("0.0001"))),
        "realized_pnl_usd": str(ledger.realized_pnl), "fees_usd": str(ledger.fees),
        "open_positions": len(ledger.positions), "closed_trades": len(closed),
        "by_strategy": strategies,
        "benchmark_equal_weight_price_return": (
            str((sum(bench, ZERO) / len(bench) - 1).quantize(Decimal("0.0001")))
            if bench else "UNAVAILABLE"),
        "cash_reconciliation": {"ledger_cash": str(ledger.cash),
                                "expected_cash": str(expected_cash),
                                "status": "MATCHED" if ledger.cash == expected_cash
                                else "DISCREPANCY"},
        "kill_switch": "HALTED" if result["halted"] else "CLEAR",
        "halt_reason": result["halted"]}


# ---- orchestration ------------------------------------------------------------------------------

FIXTURE_OVERRIDE = "FIXTURE_ONLY_OVERRIDE_NOT_EVIDENCE"


def apply_fixture_override(research: StrategyResearch, strategies: frozenset[str],
                           basis: str) -> StrategyResearch:
    """Acceptance-harness only: force named strategies to ADMITTED so the execution half can
    be exercised, exactly as the SD-081 wiring test does. Refused for REAL_DATA. The real
    verdict stays in the record next to the override label."""
    if basis != FIXTURE:
        raise PipelineError("admission overrides are refused for REAL_DATA")
    admissions = []
    records = []
    for admission, record in zip(research.admissions, research.records):
        if admission.strategy_id in strategies:
            admission = replace(admission, status="ADMITTED", evidence_ref=FIXTURE_OVERRIDE,
                                oos_trades=max(admission.oos_trades, MIN_OOS_TRADES_FLOOR),
                                oos_validated=True)
            record = {**record, "admission_without_override": record["admission"],
                      "admission": "ADMITTED", "override": FIXTURE_OVERRIDE}
        admissions.append(admission)
        records.append(record)
    return replace(research, admissions=tuple(admissions), records=tuple(records))


def build_context(bundles: Sequence[tuple[dict[str, Any], str]], *, basis: str,
                  admission_through: date, cfg: PipelineConfig,
                  agent_records: Sequence[Mapping[str, Any]] = (),
                  fixture_override: frozenset[str] = frozenset()
                  ) -> tuple[StageContext, dict[str, str]]:
    """Admit each bundle (all available bars) and lock strategy admission on bars at or
    before ``admission_through`` (the replay window must start after it)."""
    if fixture_override and basis != FIXTURE:
        raise PipelineError("admission overrides are refused for REAL_DATA")
    evidence: dict[str, MarketEvidence] = {}
    research: dict[str, StrategyResearch] = {}
    excluded: dict[str, str] = {}
    latest = date(max(COMPLETE_CALENDAR_YEARS), 12, 31)
    for payload, sha in bundles:
        cid = str(payload.get("instrument_id"))
        try:
            ev = admit_market_data(payload, basis=basis, through=latest, source_sha256=sha)
            locked = admit_market_data(payload, basis=basis,
                                       through=min(admission_through, ev.last_session),
                                       source_sha256=sha)
            studied = research_strategies(locked, cfg)
            if fixture_override:
                studied = apply_fixture_override(studied, fixture_override, basis)
            research[cid] = studied
            evidence[cid] = ev
        except (PipelineError, ValueError) as exc:
            excluded[cid] = str(exc)
    if not evidence:
        raise PipelineError("no admissible market data")
    return StageContext(cfg, evidence, research, tuple(agent_records)), excluded


def _public(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _public(v) for k, v in value.items() if not str(k).startswith("_")}
    if isinstance(value, (list, tuple)):
        return [_public(v) for v in value]
    if isinstance(value, Decimal):
        return str(value)
    return value


def _decision_snapshot(ctx: StageContext, *, through: date, now: datetime) -> dict[str, Any]:
    """Run-mode decisions against an empty, throw-away simulation ledger."""
    with tempfile.TemporaryDirectory() as scratch:
        ledger = TrackLedger.open(Path(scratch) / "decision-only.sqlite3", TRACK,
                                  ctx.cfg.virtual_capital)
        return decision_pass(ctx, through=through, now=now, ledger=ledger,
                             run_key=f"run:{through.isoformat()}", scan=True)


def run_report(ctx: StageContext, excluded: Mapping[str, str], *, now: datetime,
               mode: str, admission_through: date | None = None,
               replay_result: Mapping[str, Any] | None = None,
               replay_window: tuple[date, date] | None = None) -> dict[str, Any]:
    through = max(ev.last_session for ev in ctx.evidence.values())
    snapshot = _decision_snapshot(ctx, through=through, now=now)
    basis = next(iter(ctx.evidence.values())).basis
    admitted = [f"{r.canonical_id}:{a.strategy_id}@{a.version}" for r in ctx.research.values()
                for a in r.admissions if a.status == "ADMITTED"]
    age_days = (now - session_close_utc(through)).days
    report: dict[str, Any] = {
        "schema": SCHEMA, "mode": mode, "generated_at": now.isoformat(), "data_basis": basis,
        "market_data": [{"canonical_id": ev.canonical_id, "source": ev.source,
                         "bundle_sha256": ev.source_sha256, "first": str(ev.bars[0].day),
                         "last": str(ev.last_session), "sessions": len(ev.bars),
                         "limitations": list(ev.limitations)} for ev in ctx.evidence.values()],
        "excluded_instruments": dict(excluded),
        "data_freshness": {"latest_session": str(through), "age_days_at_run": age_days,
                           "status": ("STALE_FOR_EXECUTION"
                                      if age_days > STALE_FOR_EXECUTION_DAYS else "CURRENT")},
        "admission_through": None if admission_through is None else str(admission_through),
        "strategies": [rec for r in ctx.research.values() for rec in r.records],
        "benchmarks": {cid: r.benchmark for cid, r in ctx.research.items()},
        "admitted_strategies": admitted, **_public(snapshot),
        "broker_routes": dict(BROKER_ROUTES),
        "execution": {"route": ctx.cfg.route, "orders_submitted_to_a_broker": 0,
                      "real_money": "PROHIBITED"}}
    if replay_result is not None and replay_window is not None:
        report["replay"] = {"events": _public(replay_result["events"])[-500:],
                            "positions": _public(replay_result["attribution"]),
                            "performance": performance(replay_result, ctx,
                                                       start=replay_window[0],
                                                       end=replay_window[1])}
    report["gates"] = gates(report)
    return report


def gates(report: Mapping[str, Any]) -> dict[str, str]:
    real = report["data_basis"] == REAL_DATA
    return {
        "ENGINEERING": "NOT_ASSESSED_HERE (see exact-HEAD CI)",
        "REAL_DATA": ("VERIFIED (admitted daily bars; research-only limitations listed)"
                      if real else "NOT_ASSESSED (fixture run)"),
        "STRATEGY_ADMISSION": (("VERIFIED" if report["admitted_strategies"] else
                                "BLOCKED (no strategy meets the admission floor on genuine data)")
                               if real else "NOT_ASSESSED (fixture admission is not evidence)"),
        "AI_RESEARCH": ("VERIFIED" if real and any(a["status"] == "SIGNAL"
                                                   for a in report["agents"])
                        else "BLOCKED (no authorized agent run; provider approval required)"),
        "BROKER": "BLOCKED (no broker-confirmed Demo round trip yet)",
        "PAPER_EXECUTION": "BLOCKED (no owner-released Demo policy; SD-074F not wired)",
        "FORWARD_TESTING": "NOT_ASSESSED (simulated replay only; no observed Demo trading)",
    }


def write_report(report: Mapping[str, Any], folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(report, indent=2, sort_keys=True, default=str).encode("utf-8")
    stamp = str(report["generated_at"])[:19].replace(":", "")
    target = folder / f"run-{report['mode']}-{stamp}-{_sha(encoded)[:8]}.json"
    target.write_bytes(encoded)
    latest = folder / "latest-run.json"
    temporary = latest.with_suffix(".tmp")
    temporary.write_bytes(encoded)
    temporary.replace(latest)
    return target


# ---- synthetic fixtures (acceptance harness only) ------------------------------------------------

def synthetic_bundle(ticker: str, *, start: date, end: date, seed: int = 1) -> dict[str, Any]:
    """Deterministic two-frequency series on real XNYS sessions, labelled SYNTHETIC_FIXTURE,
    with a gap-down shock every 37 sessions so stops are exercised. It exists to exercise the
    admission and execution code paths; it is never market evidence."""
    venues = {"SPY": "NYSE_ARCA", "QQQ": "NASDAQ", "MSFT": "NASDAQ", "AAPL": "NASDAQ"}
    records = []
    base = Decimal(100 + seed * 7)
    for index, day in enumerate(expected_regular_sessions(start, end)):
        fast = math.sin(2 * math.pi * (index + seed) / 5)
        slow = math.sin(2 * math.pi * (index + 11 * seed) / 90)
        shock = Decimal("0.06") if (index + 3 * seed) % 37 == 0 else ZERO
        level = Decimal(str(round(1 + 0.02 * fast + 0.2 * slow, 6)))
        close = (base * (level - shock)).quantize(CENT)
        open_ = (close * (1 - shock / 2)).quantize(CENT)
        high = (max(open_, close) * Decimal("1.004")).quantize(CENT)
        low = (min(open_, close) * Decimal("0.996")).quantize(CENT)
        records.append({"date": day.isoformat(), "timestamp": f"{day.isoformat()}T04:00:00Z",
                        "open": str(open_), "high": str(high), "low": str(low),
                        "close": str(close), "volume": str(5_000_000 + index % 13 * 1000),
                        "ticker": ticker, "source_id": f"fixture:{ticker}:{day.isoformat()}"})
    return {"ticker": ticker, "instrument_id": f"US:{ticker}", "exchange": venues[ticker],
            "currency": "USD", "session": "REGULAR", "adjustment": "split_adjusted",
            "source": "sidedeck-synthetic-fixture", "synthetic_fixture": True,
            "admission_status": "SYNTHETIC_FIXTURE", "corporate_actions_verified": False,
            "records": records}


ACCEPTANCE_START = date(2022, 1, 3)
ACCEPTANCE_ADMISSION_THROUGH = date(2026, 4, 30)
ACCEPTANCE_WINDOW = (date(2026, 5, 1), date(2026, 10, 23))


def fixture_context(*, override: frozenset[str] = frozenset({"channel_mean_reversion"}),
                    **changes: Any) -> tuple[StageContext, dict[str, str]]:
    bundles = []
    for seed, ticker in enumerate(("SPY", "QQQ", "MSFT"), start=1):
        payload = synthetic_bundle(ticker, start=ACCEPTANCE_START, end=ACCEPTANCE_WINDOW[1],
                                   seed=seed)
        bundles.append((payload, _sha(payload)))
    cfg = PipelineConfig(broker_mappings={f"US:{t}": "FIXTURE_MAPPING" for t in
                                          ("SPY", "QQQ", "MSFT")}, **changes)
    return build_context(bundles, basis=FIXTURE,
                         admission_through=ACCEPTANCE_ADMISSION_THROUGH, cfg=cfg,
                         fixture_override=override)


def acceptance(workdir: Path, *, broker: SimulatedBroker | None = None) -> dict[str, Any]:
    """End-to-end harness on labelled fixtures through the production decision/risk code."""
    ctx, excluded = fixture_context()
    result = replay(ctx, start=ACCEPTANCE_WINDOW[0], end=ACCEPTANCE_WINDOW[1],
                    workdir=workdir / "replay", broker=broker)
    moment = session_close_utc(ACCEPTANCE_WINDOW[1]) + timedelta(minutes=5)
    return run_report(ctx, excluded, now=moment, mode="acceptance",
                      admission_through=ACCEPTANCE_ADMISSION_THROUGH, replay_result=result,
                      replay_window=ACCEPTANCE_WINDOW)


def _default_mappings(data_dir: Path) -> dict[str, str]:
    mappings = {}
    msft = data_dir / "sd052-msft-instrument.json"
    if msft.is_file():
        status = str(json.loads(msft.read_text(encoding="utf-8")).get("status", ""))
        if status.startswith("RESOLVED"):
            mappings["US:MSFT"] = f"etoro-demo:1004 ({status})"
    return mappings


def main(argv: list[str] | None = None) -> int:
    from sidedeck.application.sd050_msft_instrument_lookup import DATA_DIR

    parser = argparse.ArgumentParser(description="SD-103 integrated SideDeck pipeline")
    parser.add_argument("command", choices=("run", "replay", "acceptance"))
    parser.add_argument("--bundles", nargs="*", default=[
        str(DATA_DIR / f"sd021-{t}-admitted.json") for t in ("spy", "qqq", "msft")])
    parser.add_argument("--admission-through", default="2026-04-30")
    parser.add_argument("--start", default="2026-05-01")
    parser.add_argument("--end", default="2026-10-20")
    parser.add_argument("--agent-records", default=None,
                        help="folder of agent records from separately authorized runs")
    parser.add_argument("--out", default=str(DATA_DIR / "sd103"))
    args = parser.parse_args(argv)
    out = Path(args.out)
    now = datetime.now(UTC)
    stamp = now.strftime("%Y%m%dT%H%M%S")
    try:
        if args.command == "acceptance":
            report = acceptance(out / f"acceptance-{stamp}")
        else:
            records = ([json.loads(p.read_text(encoding="utf-8"))
                        for p in sorted(Path(args.agent_records).glob("*.json"))]
                       if args.agent_records else [])
            bundles = [load_bundle(Path(p)) for p in args.bundles]
            cfg = PipelineConfig(broker_mappings=_default_mappings(DATA_DIR))
            if args.command == "replay":
                through = date.fromisoformat(args.admission_through)
                window = (date.fromisoformat(args.start), date.fromisoformat(args.end))
                if window[0] <= through:
                    raise PipelineError("replay must start after the admission lock date")
                ctx, excluded = build_context(bundles, basis=REAL_DATA,
                                              admission_through=through, cfg=cfg,
                                              agent_records=records)
                result = replay(ctx, start=window[0], end=window[1],
                                workdir=out / f"replay-{stamp}")
                report = run_report(ctx, excluded, now=now, mode="replay",
                                    admission_through=through, replay_result=result,
                                    replay_window=window)
            else:
                ctx, excluded = build_context(bundles, basis=REAL_DATA,
                                              admission_through=date(2026, 12, 31), cfg=cfg,
                                              agent_records=records)
                report = run_report(ctx, excluded, now=now, mode="run")
        path = write_report(report, out)
    except (PipelineError, ExecutionNotReleased, OSError, ValueError) as exc:
        print(json.dumps({"status": "REFUSED", "reason": f"{type(exc).__name__}: {exc}"}))
        return 5
    summary: dict[str, Any] = {
        "report": str(path), "mode": report["mode"], "data_basis": report["data_basis"],
        "data_freshness": report["data_freshness"],
        "admitted_strategies": report["admitted_strategies"],
        "decisions": [[d["symbol"], d["decision"], d["direction"], d["reasons"][:2]]
                      for d in report["decisions"]],
        "orders": len(report["orders"]), "no_trade": report["no_trade"],
        "gates": report["gates"]}
    if "replay" in report:
        perf = report["replay"]["performance"]
        summary["replay"] = {k: perf[k] for k in ("basis", "closed_trades", "total_return",
                                                  "max_drawdown", "by_strategy",
                                                  "benchmark_equal_weight_price_return",
                                                  "cash_reconciliation", "kill_switch")}
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
