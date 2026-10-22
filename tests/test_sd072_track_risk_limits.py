from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from sidedeck.application.sd072_track_risk_limits import (
    OpenDayPosition,
    RiskLimitError,
    TrackLimits,
    TrackRiskState,
    day_liquidation_plan,
    evaluate_track_risk,
)

LIMITS = TrackLimits("SWING", Decimal("0.10"), Decimal("0.03"), 4)


def _state(equity: str, peak: str = "1000", start: str = "1000", orders: int = 0) -> TrackRiskState:
    return TrackRiskState("SWING", Decimal(equity), Decimal(peak), Decimal(start), orders)


def test_within_limits_allows_entries() -> None:
    gate = evaluate_track_risk(_state("990"), LIMITS)
    assert gate.entries_allowed and gate.reasons == ()
    assert gate.drawdown_pct == Decimal("0.01") and gate.daily_loss_pct == Decimal("0.01")


@pytest.mark.parametrize("state, reason", [
    (_state("900", start="905"), "MAX_DRAWDOWN_BREACHED"),
    (_state("960"), "DAILY_LOSS_LIMIT_BREACHED"),
    (_state("1000", orders=4), "ORDER_FREQUENCY_LIMIT"),
    (_state("1100"), "INCONSISTENT_RISK_STATE"),       # equity above recorded peak
    (_state("NaN"), "INCONSISTENT_RISK_STATE"),
    (_state("500", peak="0"), "INCONSISTENT_RISK_STATE"),
])
def test_breaches_halt_new_entries(state: TrackRiskState, reason: str) -> None:
    gate = evaluate_track_risk(state, LIMITS)
    assert not gate.entries_allowed and reason in gate.reasons


def test_limits_validation_and_track_mismatch() -> None:
    with pytest.raises(RiskLimitError):
        TrackLimits("DAY", Decimal("1"), Decimal("0.02"), 3)
    with pytest.raises(RiskLimitError):
        TrackLimits("DAY", Decimal("0.1"), Decimal("0.02"), -1)
    with pytest.raises(RiskLimitError):
        evaluate_track_risk(TrackRiskState("DAY", *(Decimal(1),) * 3, 0), LIMITS)


CLOSE = datetime(2026, 10, 22, 20, 0, tzinfo=UTC)          # 16:00 New York (EDT)
POS = (OpenDayPosition("p1", "US:AAA", CLOSE - timedelta(hours=3)),)


@pytest.mark.parametrize("now, phase, liquidate, unresolved", [
    (CLOSE - timedelta(hours=2), "NONE", (), ()),
    (CLOSE - timedelta(minutes=20), "NO_NEW_ENTRIES", (), ()),
    (CLOSE - timedelta(minutes=10), "LIQUIDATE_NOW", ("p1",), ()),
    (CLOSE + timedelta(minutes=1), "UNRESOLVED_AFTER_CLOSE", (), ("p1",)),
])
def test_day_liquidation_phases(now: datetime, phase: str, liquidate: tuple[str, ...],
                                unresolved: tuple[str, ...]) -> None:
    plan = day_liquidation_plan(POS, now)
    assert (plan.phase, plan.liquidate, plan.unresolved) == (phase, liquidate, unresolved)


def test_early_close_and_overnight_positions() -> None:
    early_close = datetime(2026, 11, 27, 18, 0, tzinfo=UTC)  # 13:00 New York
    pos = (OpenDayPosition("p2", "US:AAA", early_close - timedelta(hours=2)),)
    plan = day_liquidation_plan(pos, early_close - timedelta(minutes=10))
    assert plan.phase == "LIQUIDATE_NOW" and plan.session_close == early_close
    next_day = day_liquidation_plan(POS, datetime(2026, 10, 23, 14, tzinfo=UTC))
    assert next_day.phase == "UNRESOLVED_AFTER_CLOSE" and next_day.unresolved == ("p1",)
    holiday = day_liquidation_plan(POS, datetime(2026, 11, 26, 16, tzinfo=UTC))
    assert holiday.phase == "UNRESOLVED_AFTER_CLOSE"
    assert day_liquidation_plan((), datetime(2026, 11, 26, 16, tzinfo=UTC)).phase == "NONE"
    with pytest.raises(RiskLimitError):
        day_liquidation_plan(POS, CLOSE.replace(tzinfo=None))
    with pytest.raises(RiskLimitError):
        day_liquidation_plan(POS, CLOSE, no_new_entries_before_close=timedelta(minutes=5))
