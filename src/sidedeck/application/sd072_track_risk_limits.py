"""SD-072 per-track portfolio risk halts and DAY same-session liquidation planning.

Deterministic, offline and simulation-only. Each track is checked against its
own drawdown, daily-loss and order-frequency limits; a breach halts *new
entries* for that track only. DAY positions must be flat before the session
close: the planner lists what must be liquidated, and anything still open after
the close is reported ``UNRESOLVED`` (kill-switch territory), never silently
converted into a SWING position.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from sidedeck.application.sd068_track_scheduler import NEW_YORK, session_for

ZERO = Decimal(0)


class RiskLimitError(ValueError):
    pass


@dataclass(frozen=True)
class TrackLimits:
    track: str
    max_drawdown_pct: Decimal
    max_daily_loss_pct: Decimal
    max_orders_per_day: int

    def __post_init__(self) -> None:
        for value in (self.max_drawdown_pct, self.max_daily_loss_pct):
            if not value.is_finite() or not ZERO < value < 1:
                raise RiskLimitError("loss limits must be in (0, 1)")
        if self.max_orders_per_day < 0:
            raise RiskLimitError("order frequency limit must be non-negative")


@dataclass(frozen=True)
class TrackRiskState:
    track: str
    equity: Decimal
    peak_equity: Decimal
    session_start_equity: Decimal
    orders_today: int


@dataclass(frozen=True)
class RiskGate:
    track: str
    entries_allowed: bool
    reasons: tuple[str, ...]
    drawdown_pct: Decimal
    daily_loss_pct: Decimal


def evaluate_track_risk(state: TrackRiskState, limits: TrackLimits) -> RiskGate:
    if state.track != limits.track:
        raise RiskLimitError("limits belong to a different track")
    values = (state.equity, state.peak_equity, state.session_start_equity)
    if any(not v.is_finite() or v < 0 for v in values) or state.peak_equity <= 0 \
            or state.session_start_equity <= 0 or state.equity > state.peak_equity:
        # Inconsistent accounting state halts the track rather than guessing.
        return RiskGate(state.track, False, ("INCONSISTENT_RISK_STATE",), ZERO, ZERO)
    drawdown = (state.peak_equity - state.equity) / state.peak_equity
    daily_loss = max(ZERO, (state.session_start_equity - state.equity) / state.session_start_equity)
    reasons: list[str] = []
    if drawdown >= limits.max_drawdown_pct:
        reasons.append("MAX_DRAWDOWN_BREACHED")
    if daily_loss >= limits.max_daily_loss_pct:
        reasons.append("DAILY_LOSS_LIMIT_BREACHED")
    if state.orders_today >= limits.max_orders_per_day:
        reasons.append("ORDER_FREQUENCY_LIMIT")
    return RiskGate(state.track, not reasons, tuple(reasons), drawdown, daily_loss)


@dataclass(frozen=True)
class OpenDayPosition:
    position_ref: str
    canonical_id: str
    opened_at: datetime


@dataclass(frozen=True)
class LiquidationPlan:
    phase: str  # NONE | NO_NEW_ENTRIES | LIQUIDATE_NOW | UNRESOLVED_AFTER_CLOSE
    liquidate: tuple[str, ...]
    unresolved: tuple[str, ...]
    session_close: datetime | None


def day_liquidation_plan(
    positions: tuple[OpenDayPosition, ...], now: datetime, *,
    no_new_entries_before_close: timedelta = timedelta(minutes=30),
    liquidate_before_close: timedelta = timedelta(minutes=15),
) -> LiquidationPlan:
    """What the DAY track must do now. Early closes are honoured via the calendar."""
    if now.tzinfo is None:
        raise RiskLimitError("timezone-aware time required")
    if liquidate_before_close > no_new_entries_before_close:
        raise RiskLimitError("liquidation must start after new entries stop")
    refs = tuple(sorted(p.position_ref for p in positions))
    session = session_for(now.astimezone(NEW_YORK).date())
    # Any DAY position from an earlier session is unresolved regardless of today's state.
    stale = tuple(sorted(
        p.position_ref for p in positions
        if session is None or p.opened_at < session.open_utc
    ))
    if stale:
        return LiquidationPlan("UNRESOLVED_AFTER_CLOSE", (), stale,
                               session.close_utc if session else None)
    if session is None:
        return LiquidationPlan("NONE", (), (), None)
    if now >= session.close_utc:
        phase = "UNRESOLVED_AFTER_CLOSE" if refs else "NONE"
        return LiquidationPlan(phase, (), refs, session.close_utc)
    if now >= session.close_utc - liquidate_before_close:
        return LiquidationPlan("LIQUIDATE_NOW" if refs else "NO_NEW_ENTRIES", refs, (),
                               session.close_utc)
    if now >= session.close_utc - no_new_entries_before_close:
        return LiquidationPlan("NO_NEW_ENTRIES", (), (), session.close_utc)
    return LiquidationPlan("NONE", (), (), session.close_utc)
