"""SD-071/072 deterministic portfolio decision engine with per-track capital.

Combines normalized research signals with strategy admission evidence and
deterministic portfolio constraints. Output is one of ``ELIGIBLE``,
``WATCHLIST``, ``ABSTAIN`` or ``REJECTED`` with explicit reasons.

``ELIGIBLE`` means *eligible for review by a separately authorized execution
service*. The engine never grants execution permission, never places orders and
cannot be configured to do so. Agent-only agreement can at most reach
``WATCHLIST``: agreement between research agents is not proof of an edge.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from typing import Mapping, Sequence

from sidedeck.application.sd070_research_signal import TRACK_HORIZONS, ResearchSignal

EXECUTION_PERMISSION = "NOT_GRANTED_BY_DECISION_ENGINE"
MIN_OOS_TRADES_FLOOR = 30  # admission can be stricter per strategy, never looser
STATUSES = ("ELIGIBLE", "WATCHLIST", "ABSTAIN", "REJECTED")
ZERO = Decimal(0)


class DecisionError(ValueError):
    pass


@dataclass(frozen=True)
class StrategyAdmission:
    strategy_id: str
    version: str
    track: str
    status: str  # ADMITTED | RESEARCH_ONLY | REJECTED
    evidence_ref: str
    oos_trades: int
    oos_validated: bool
    min_oos_trades: int = 30

    def __post_init__(self) -> None:
        if self.status not in ("ADMITTED", "RESEARCH_ONLY", "REJECTED"):
            raise DecisionError("invalid admission status")
        if self.status == "ADMITTED" and not (
            self.oos_validated
            and self.oos_trades >= max(self.min_oos_trades, MIN_OOS_TRADES_FLOOR)
            and self.evidence_ref.strip()
        ):
            raise DecisionError(
                "admission requires locked out-of-sample validation, enough trades and evidence"
            )


@dataclass(frozen=True)
class TrackPolicy:
    policy_id: str
    track: str
    virtual_capital: Decimal
    max_position_pct: Decimal
    max_positions: int
    max_gross_exposure_pct: Decimal
    max_instrument_total_pct: Decimal  # across all tracks, of this track's capital
    max_sector_pct: Decimal
    max_correlation: Decimal
    risk_per_trade_pct: Decimal
    stop_atr_multiple: Decimal
    min_notional: Decimal
    max_signal_age: timedelta
    max_signal_data_age: timedelta  # age of the signal's data cutoff
    max_price_age: timedelta
    expires_at: datetime
    allowed_strategies: frozenset[tuple[str, str]]
    allowed_instruments: frozenset[str] | None = None

    def __post_init__(self) -> None:
        if self.track not in TRACK_HORIZONS:
            raise DecisionError("unknown track")
        pcts = (self.max_position_pct, self.max_gross_exposure_pct, self.max_instrument_total_pct,
                self.max_sector_pct, self.risk_per_trade_pct)
        if any(not p.is_finite() or p <= 0 or p > 1 for p in pcts):
            raise DecisionError("percentages must be in (0, 1]")
        if self.virtual_capital <= 0 or self.min_notional <= 0 or self.max_positions < 1:
            raise DecisionError("invalid capital or position limits")
        if self.stop_atr_multiple <= 0 or not ZERO < self.max_correlation <= 1:
            raise DecisionError("invalid stop or correlation limit")
        if self.expires_at.tzinfo is None:
            raise DecisionError("policy expiry must be timezone-aware")


@dataclass(frozen=True)
class Holding:
    canonical_id: str
    track: str
    notional: Decimal
    sector: str


@dataclass(frozen=True)
class PortfolioState:
    holdings: tuple[Holding, ...]
    cash_by_track: Mapping[str, Decimal]


@dataclass(frozen=True)
class MarketContext:
    canonical_id: str
    last_price: Decimal
    price_time: datetime
    atr: Decimal
    sector: str
    session_open: bool
    execution_eligible: bool  # from SD-065 BROKER_EXECUTION_ELIGIBLE
    correlations: Mapping[str, Decimal] = field(default_factory=dict)


@dataclass(frozen=True)
class SizingProposal:
    quantity: Decimal
    notional: Decimal
    stop_price: Decimal
    horizon_max_days: int
    exit_rule: str


@dataclass(frozen=True)
class Decision:
    status: str
    canonical_id: str
    track: str
    policy_id: str
    decided_at: datetime
    reasons: tuple[str, ...]
    qualified_signal_ids: tuple[str, ...] = ()
    supporting_signal_ids: tuple[str, ...] = ()
    disagreements: tuple[str, ...] = ()
    sizing: SizingProposal | None = None
    execution_permission: str = EXECUTION_PERMISSION

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise DecisionError("invalid decision status")
        if self.execution_permission != EXECUTION_PERMISSION:
            raise DecisionError("the decision engine cannot grant execution permission")
        if (self.status == "ELIGIBLE") != (self.sizing is not None):
            raise DecisionError("only ELIGIBLE decisions carry sizing")


def decide(
    signals: Sequence[ResearchSignal],
    admissions: Sequence[StrategyAdmission],
    policy: TrackPolicy,
    portfolio: PortfolioState,
    market: MarketContext,
    now: datetime,
) -> Decision:
    if now.tzinfo is None:
        raise DecisionError("timezone-aware time required")
    cid, track = market.canonical_id, policy.track

    def out(status: str, *reasons: str, **kw: object) -> Decision:
        return Decision(status, cid, track, policy.policy_id, now, tuple(reasons), **kw)  # type: ignore[arg-type]

    reasons: list[str] = []
    relevant: list[ResearchSignal] = []
    for s in signals:
        if s.canonical_id != cid:
            continue
        if s.track != track:
            reasons.append(f"IGNORED_OTHER_TRACK:{s.track}")  # no cross-horizon reuse
            continue
        if s.generated_at > now:
            return out("REJECTED", "FUTURE_DATED_SIGNAL")
        if now - s.generated_at > policy.max_signal_age:
            reasons.append(f"STALE_SIGNAL:{s.source_id}")
            continue
        if now - s.data_cutoff > policy.max_signal_data_age:
            reasons.append(f"STALE_SIGNAL_DATA:{s.source_id}")
            continue
        relevant.append(s)
    if not relevant:
        return out("ABSTAIN", "NO_CURRENT_SIGNAL", *reasons)

    admitted = {
        (a.strategy_id, a.version) for a in admissions
        if a.track == track and a.status == "ADMITTED"
    }
    qualified = [s for s in relevant if s.source_kind == "NATIVE_STRATEGY"
                 and (s.source_id, s.source_version) in admitted]
    supporting = [s for s in relevant if s not in qualified]
    q_dirs = {s.direction for s in qualified if s.direction in ("LONG", "SHORT")}
    disagreements = tuple(sorted(
        f"{s.source_kind}:{s.source_id}:{s.direction}" for s in supporting
        if s.direction in ("SHORT", "LONG") and q_dirs and s.direction not in q_dirs
    ))
    ids = {
        "qualified_signal_ids": tuple(sorted(s.signal_id for s in qualified)),
        "supporting_signal_ids": tuple(sorted(s.signal_id for s in supporting)),
        "disagreements": disagreements,
    }
    if q_dirs == {"LONG", "SHORT"}:
        return out("ABSTAIN", "QUALIFIED_SIGNALS_CONFLICT", *reasons, **ids)
    if q_dirs == {"SHORT"}:
        return out("REJECTED", "LONG_ONLY_POLICY", *reasons, **ids)
    if not q_dirs:
        if any(s.direction == "LONG" for s in supporting):
            return out("WATCHLIST", "NO_ADMITTED_STRATEGY_SIGNAL",
                       "AGENT_AGREEMENT_IS_NOT_PROOF_OF_EDGE", *reasons, **ids)
        return out("ABSTAIN", "NO_DIRECTIONAL_QUALIFIED_SIGNAL", *reasons, **ids)
    if disagreements:
        return out("WATCHLIST", "RESEARCH_DISAGREEMENT", *reasons, **ids)

    # From here a qualified LONG exists; apply deterministic constraints.
    if now >= policy.expires_at:
        return out("REJECTED", "POLICY_EXPIRED", **ids)
    if not any((s.source_id, s.source_version) in policy.allowed_strategies for s in qualified):
        return out("REJECTED", "STRATEGY_NOT_IN_POLICY_SCOPE", **ids)
    if policy.allowed_instruments is not None and cid not in policy.allowed_instruments:
        return out("REJECTED", "INSTRUMENT_NOT_IN_POLICY_SCOPE", **ids)
    if market.price_time.tzinfo is None:
        raise DecisionError("market price time must be timezone-aware")
    if market.price_time > now or now - market.price_time > policy.max_price_age:
        return out("REJECTED", "STALE_OR_FUTURE_MARKET_DATA", **ids)
    if not (market.last_price.is_finite() and market.last_price > 0
            and market.atr.is_finite() and market.atr > 0):
        return out("REJECTED", "INVALID_MARKET_DATA", **ids)
    if track == "DAY" and not market.session_open:
        return out("REJECTED", "OUTSIDE_TRADING_HOURS", **ids)
    track_holdings = [h for h in portfolio.holdings if h.track == track]
    if any(h.canonical_id == cid for h in track_holdings):
        return out("REJECTED", "ALREADY_HELD_IN_TRACK", **ids)
    if len(track_holdings) >= policy.max_positions:
        return out("REJECTED", "MAX_POSITIONS", **ids)
    for h in track_holdings:
        corr = market.correlations.get(h.canonical_id)
        # Missing or invalid correlation evidence fails closed.
        if corr is None or not corr.is_finite() or not Decimal(-1) <= corr <= Decimal(1):
            return out("REJECTED", f"MISSING_CORRELATION:{h.canonical_id}", **ids)
        if corr > policy.max_correlation:
            return out("REJECTED", f"CORRELATED_WITH_HOLDING:{h.canonical_id}", **ids)

    cap = policy.virtual_capital
    stop_distance = market.atr * policy.stop_atr_multiple
    if stop_distance >= market.last_price:
        return out("REJECTED", "STOP_DISTANCE_EXCEEDS_PRICE", **ids)
    gross = sum((h.notional for h in track_holdings), ZERO)
    instrument_total = sum((h.notional for h in portfolio.holdings if h.canonical_id == cid), ZERO)
    sector_total = sum((h.notional for h in track_holdings if h.sector == market.sector), ZERO)
    cash = portfolio.cash_by_track.get(track, ZERO)
    limits = {
        "RISK_BUDGET": cap * policy.risk_per_trade_pct / stop_distance * market.last_price,
        "MAX_POSITION": cap * policy.max_position_pct,
        "CASH": cash,
        "GROSS_EXPOSURE": cap * policy.max_gross_exposure_pct - gross,
        "INSTRUMENT_TOTAL": cap * policy.max_instrument_total_pct - instrument_total,
        "SECTOR": cap * policy.max_sector_pct - sector_total,
    }
    binding = min(limits, key=lambda k: (limits[k], k))
    notional_cap = limits[binding]
    quantity = (notional_cap / market.last_price).quantize(Decimal("0.0001"), rounding=ROUND_DOWN)
    notional = (quantity * market.last_price).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    if quantity <= 0 or notional < policy.min_notional:
        return out("REJECTED", f"INSUFFICIENT_CAPACITY:{binding}", **ids)
    if not market.execution_eligible:
        return out("WATCHLIST", "NOT_BROKER_EXECUTION_ELIGIBLE", **ids)
    horizon = max(s.horizon_max_days for s in qualified)
    exit_rule = ("SAME_SESSION_LIQUIDATION" if track == "DAY"
                 else f"STOP_OR_TIME_EXIT_{horizon}_TRADING_DAYS")
    sizing = SizingProposal(quantity, notional, market.last_price - stop_distance, horizon, exit_rule)
    return out("ELIGIBLE", f"BINDING_LIMIT:{binding}", *reasons, sizing=sizing, **ids)
