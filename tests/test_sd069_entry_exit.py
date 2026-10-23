"""SD-069 entry timer and exit planner, checked against the day-trader-skill 2.0.0 worked
examples (TSLA, Monday 2026-10-19) plus refusals and calendar edges. Synthetic bars only."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from sidedeck.application.sd069_day_trader_methods import IntradayBar, MethodError
from sidedeck.application.sd069_entry_exit import entry_trigger, exit_plan

UTC = timezone.utc
OPEN = datetime(2026, 10, 19, 13, 30, tzinfo=UTC)          # 09:30 New York (EDT)
D = Decimal


def _bar(i: int, close: str, *, high: str | None = None, low: str | None = None,
         volume: str = "1000") -> IntradayBar:
    c = D(close)
    return IntradayBar(OPEN + timedelta(minutes=5 * i), c, D(high) if high else c,
                       D(low) if low else c, c, D(volume))


def _reel() -> list[IntradayBar]:
    bars = [_bar(0, "358", high="362.18", low="354.47"), _bar(1, "360", high="361", low="356"),
            _bar(2, "359", high="360", low="355")]                       # 09:30-09:40 range
    bars += [_bar(i, "361") for i in range(3, 7)]                      # 09:45-10:00
    bars += [_bar(7, "361.68")]                                        # 10:05 bar
    bars += [_bar(8, "364.18", volume="600")]                          # 10:10 bar, thin
    bars += [_bar(i, "362.00") for i in range(9, 12)]                  # 10:15-10:25 below
    bars += [_bar(12, "365.75", volume="7980")]                        # 10:30 bar, heavy
    return bars


def _ny(hour: int, minute: int, day: datetime = OPEN) -> datetime:
    return day.replace(hour=hour + 4, minute=minute)                   # EDT = UTC-4


# --- entry -----------------------------------------------------------------------------------

def test_reel_waits_until_the_trigger_bar_has_closed():
    status = entry_trigger(_reel(), _ny(10, 12))
    assert status.status == "WAITING"
    assert (status.range_high, status.range_low) == (D("362.18"), D("354.47"))


def test_reel_triggers_at_the_bar_close_time_and_price():
    status = entry_trigger(_reel(), _ny(10, 15))
    assert (status.status, status.price, status.at, status.bar_index) == \
        ("TRIGGERED", D("364.18"), _ny(10, 15), 8)


def test_volume_check_moves_the_trigger_to_the_heavy_bar():
    status = entry_trigger(_reel(), _ny(10, 40), min_volume_x=D("1"))
    assert (status.status, status.price, status.at) == ("TRIGGERED", D("365.75"), _ny(10, 35))


def test_not_open_range_forming_and_level_setups():
    assert entry_trigger(_reel(), _ny(9, 20)).status == "NOT_OPEN"
    assert entry_trigger(_reel()[:2], _ny(9, 41)).status == "RANGE_FORMING"
    assert entry_trigger(_reel(), _ny(10, 40), setup="level", level=D("371.20")).status \
        == "WAITING"
    assert entry_trigger(_reel(), _ny(15, 31), setup="level", level=D("371.20")).status \
        == "EXPIRED"
    with pytest.raises(MethodError, match="level"):
        entry_trigger(_reel(), _ny(10, 40), setup="level")


def test_close_exactly_at_the_level_is_not_a_trigger():
    bars = _reel()[:8] + [_bar(8, "362.18")]
    assert entry_trigger(bars, _ny(10, 15)).status == "WAITING"


def test_no_entries_before_0945():
    bars = [_bar(0, "100", high="101", low="99"), _bar(1, "100"), _bar(2, "100")]
    bars.append(_bar(3, "102"))                                        # 09:45 bar closes 09:50
    assert entry_trigger(bars, _ny(9, 50)).status == "TRIGGERED"
    with pytest.raises(MethodError, match="opening range"):
        entry_trigger(bars, _ny(9, 50), or_minutes=7)


def test_gaps_weekends_and_naive_times_are_refused():
    bars = _reel()
    del bars[5]
    with pytest.raises(MethodError, match="missing or off-grid"):
        entry_trigger(bars, _ny(10, 40))
    with pytest.raises(MethodError, match="market closed"):
        entry_trigger(_reel(), datetime(2026, 10, 24, 15, 0, tzinfo=UTC))
    with pytest.raises(MethodError, match="timezone"):
        entry_trigger(_reel(), datetime(2026, 10, 19, 14, 0))


def test_early_close_moves_the_entry_cutoff():
    day = datetime(2026, 11, 27, 14, 30, tzinfo=UTC)                   # 09:30 EST, 13:00 close
    bars = [IntradayBar(day + timedelta(minutes=5 * i), D("100"), D("101") if i == 0 else D("100"),
                        D("99") if i == 0 else D("100"), D("100"), D("1000"))
            for i in range(0, 42)]
    late = datetime(2026, 11, 27, 17, 31, tzinfo=UTC)                  # 12:31 EST
    assert entry_trigger(bars, late).status == "EXPIRED"


# --- exit ------------------------------------------------------------------------------------

def test_reel_exit_plan_or_mid_stop_and_1r_target():
    plan = exit_plan(entry=D("364.18"), entry_at=_ny(10, 15), stop_rule="or-mid",
                     target_rule="1R", range_high=D("362.18"), range_low=D("354.47"))
    assert (plan.stop, plan.target, plan.risk_per_share, plan.risk_pct, plan.reward_risk) == \
        (D("358.32"), D("370.04"), D("5.86"), D("1.61"), D("1.00"))
    assert plan.flat_by == _ny(15, 55)


def test_default_2r_target_and_other_stops():
    plan = exit_plan(entry=D("364.18"), entry_at=_ny(10, 15), range_high=D("362.18"),
                     range_low=D("354.47"))
    assert plan.target == D("375.90")
    assert exit_plan(entry=D("100"), entry_at=_ny(10, 15), stop_rule="pct:2").stop == D("98.00")
    assert exit_plan(entry=D("100"), entry_at=_ny(10, 15), stop_rule="price:97.555").stop \
        == D("97.55")                                                  # rounded down
    assert exit_plan(entry=D("364.18"), entry_at=_ny(10, 15), stop_rule="or-low",
                     range_high=D("362.18"), range_low=D("354.47")).stop == D("354.47")


def test_atr_stop_uses_up_to_14_session_bars_and_reports_fewer():
    plan = exit_plan(entry=D("364.18"), entry_at=_ny(10, 15), stop_rule="atr:1.5",
                     session_bars=_reel())
    assert "fewer than 14" in plan.note
    assert plan.stop < D("364.18")


@pytest.mark.parametrize("kwargs, reason", [
    ({"stop_rule": "price:364.18"}, "at or above the entry"),
    ({"stop_rule": "price:364.10"}, "too tight"),
    ({"stop_rule": "price:350", "target_rule": "price:364.18"}, "target at or below"),
    ({"stop_rule": "or-mid", "setup": "level"}, "name a stop"),
    ({"stop_rule": "or-mid"}, "opening range is required"),
    ({"stop_rule": "bogus"}, "unknown stop rule"),
    ({"stop_rule": "pct:abc"}, "malformed stop rule"),
    ({"stop_rule": "price:350", "target_rule": "0R"}, "positive"),
    ({"stop_rule": "atr:1.5"}, "ATR stop needs"),
])
def test_exit_refusals_say_why(kwargs, reason):
    with pytest.raises(MethodError, match=reason):
        exit_plan(entry=D("364.18"), entry_at=_ny(10, 15), **kwargs)


def test_flat_by_refuses_late_entries_and_moves_on_early_close():
    with pytest.raises(MethodError, match="flat-by"):
        exit_plan(entry=D("100"), entry_at=_ny(15, 55), stop_rule="pct:1")
    early = exit_plan(entry=D("100"), entry_at=datetime(2026, 11, 27, 15, 0, tzinfo=UTC),
                      stop_rule="pct:1")
    assert early.flat_by == datetime(2026, 11, 27, 17, 55, tzinfo=UTC)  # 12:55 EST
