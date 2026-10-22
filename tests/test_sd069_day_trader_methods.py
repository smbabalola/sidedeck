"""SD-069 native day-trader methodology. All bars are synthetic fixtures."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from sidedeck.application.sd014_strategy_engine import StrategyBar
from sidedeck.application.sd069_day_trader_methods import (
    IntradayBar,
    MethodError,
    daily_setups,
    daily_signals,
    opening_range_breakout,
    orb_signal,
    wilder_rsi,
)
from sidedeck.application.sd071_decision_engine import decide
from sidedeck.application.us_equity_calendar import expected_regular_sessions

CUTOFF = date(2026, 10, 21)
DAYS = expected_regular_sessions(date(2026, 7, 1), CUTOFF)


def _bars(closes: list[str]) -> tuple[StrategyBar, ...]:
    days = DAYS[-len(closes):]
    return tuple(
        StrategyBar(d, Decimal(c), Decimal(c) * Decimal("1.01"), Decimal(c) * Decimal("0.99"),
                    Decimal(c), Decimal(1_000_000))
        for d, c in zip(days, closes)
    )


def test_wilder_rsi_matches_reference_values() -> None:
    assert wilder_rsi([Decimal(1)] * 10) is None
    assert wilder_rsi([Decimal(i) for i in range(1, 20)]) == Decimal(100)
    falling = [Decimal(100 - i) for i in range(30)]
    rsi = wilder_rsi(falling)
    assert rsi is not None and rsi == Decimal(0)


def test_breakout_and_reclaim() -> None:
    closes = ["100"] * 20 + ["99", "105"]
    hits = daily_setups(_bars(closes), CUTOFF)
    assert "breakout_20d" in hits and "reclaim_ma20" in hits
    assert "100" in hits["breakout_20d"]
    flat = daily_setups(_bars(["100"] * 22), CUTOFF)
    assert "breakout_20d" not in flat


def test_bull_flag() -> None:
    closes = ["100"] * 6 + [str(100 + 2 * i) for i in range(1, 11)] + [
        "119", "120", "119.5", "120.5", "120"]
    assert "bull_flag" in daily_setups(_bars(closes), CUTOFF)
    wide = closes[:-5] + ["110", "125", "112", "126", "111"]
    assert "bull_flag" not in daily_setups(_bars(wide), CUTOFF)


def test_oversold_and_bounce() -> None:
    falling = [str(100 - i) for i in range(25)]
    assert "oversold" in daily_setups(_bars(falling), CUTOFF)
    bounce = falling[:-1] + [str(int(falling[-2]) + 1)]
    hits = daily_setups(_bars(bounce), CUTOFF)
    assert "oversold_bounce" in hits


def test_daily_series_must_end_at_cutoff_and_not_after() -> None:
    bars = _bars(["100"] * 25)
    with pytest.raises(MethodError, match="stale"):
        daily_setups(bars[:-1], CUTOFF)
    future = bars + (StrategyBar(date(2026, 10, 22), *([Decimal(100)] * 5)),)
    with pytest.raises(MethodError, match="look-ahead"):
        daily_setups(future, CUTOFF)


def test_daily_signals_are_swing_research_and_capped_at_watchlist() -> None:
    from tests.test_sd070_sd071_signals_decisions import ADMIT, EMPTY, MARKET, POLICY

    gen = datetime(2026, 10, 22, 12, tzinfo=UTC)
    cutoff_time = datetime(2026, 10, 21, 20, tzinfo=UTC)
    signals = daily_signals("US:AAA", _bars(["100"] * 20 + ["99", "105"]), CUTOFF,
                            cutoff_time=cutoff_time, generated_at=gen)
    # The one-day dip after a flat run also gives RSI 0 yesterday, so the bounce rule matches.
    assert {s.source_id for s in signals} == {"day_trader_skill.breakout_20d",
                                              "day_trader_skill.reclaim_ma20",
                                              "day_trader_skill.oversold_bounce"}
    assert all(s.track == "SWING" and s.source_kind == "DAY_TRADER_METHOD" for s in signals)
    assert all("not a recommendation" in s.rationale for s in signals)
    decision = decide(signals, [ADMIT], POLICY, EMPTY, MARKET, gen + timedelta(hours=1))
    assert decision.status == "WATCHLIST" and decision.sizing is None


OPEN = datetime(2026, 10, 22, 13, 30, tzinfo=UTC)  # 09:30 New York (EDT)


def _intraday(highs_closes: list[tuple[str, str]]) -> list[IntradayBar]:
    out = []
    for i, (high, close) in enumerate(highs_closes):
        h, c = Decimal(high), Decimal(close)
        out.append(IntradayBar(OPEN + timedelta(minutes=5 * i), c, h, c - 1, c, Decimal(1000)))
    return out


def test_orb_uses_completed_bars_only() -> None:
    bars = _intraday([("101", "100"), ("102", "101"), ("101.5", "100.5"),
                      ("102", "101.8"), ("104", "103")])
    # 5th bar (09:50-09:55) closes above the 102 range high; complete at 09:55.
    assert opening_range_breakout(bars, OPEN + timedelta(minutes=24)) is None
    hit = opening_range_breakout(bars, OPEN + timedelta(minutes=25))
    assert hit and hit.range_high == Decimal(102) and hit.hit_at == OPEN + timedelta(minutes=25)
    assert opening_range_breakout(bars[:2], OPEN + timedelta(minutes=12)) is None  # range open


def test_orb_refuses_gaps_holidays_and_naive_time() -> None:
    bars = _intraday([("101", "100"), ("102", "101"), ("101.5", "100.5"), ("104", "103")])
    gapped = bars[:2] + bars[3:]
    with pytest.raises(MethodError, match="missing"):
        opening_range_breakout(gapped, OPEN + timedelta(minutes=30))
    with pytest.raises(MethodError, match="no regular session"):
        opening_range_breakout(bars, datetime(2026, 11, 26, 16, tzinfo=UTC))
    with pytest.raises(MethodError):
        opening_range_breakout(bars, datetime(2026, 10, 22, 14))
    with pytest.raises(MethodError):
        opening_range_breakout(bars, OPEN + timedelta(minutes=30), or_minutes=7)


def test_orb_signal_is_day_track_with_invalidation() -> None:
    bars = _intraday([("101", "100"), ("102", "101"), ("101.5", "100.5"), ("104", "103")])
    now = OPEN + timedelta(minutes=21)
    signal = orb_signal("US:AAA", bars, now)
    assert signal and signal.track == "DAY" and signal.horizon_max_days == 0
    assert signal.data_cutoff == OPEN + timedelta(minutes=20) and len(signal.invalidation) == 2
