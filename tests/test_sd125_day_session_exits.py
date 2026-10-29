"""SD-125: DAY orders use the actual daily exchange session, never policy expiry."""
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from sidedeck.application.sd063_autonomous_demo_policy import (
    EntryProposal, Refusal, StrategyScope,
)
from sidedeck.application.sd068_track_scheduler import session_for
from sidedeck.application.sd070_research_signal import EvidenceRef, ResearchSignal
from sidedeck.application.sd071_decision_engine import StrategyAdmission

from test_sd063_autonomous_demo_policy import (
    EVIDENCE_SHA, MSFT, SHA, _Env, _budget, _fill, _policy,
)


def _day_env(tmp_path: Path, when: datetime) -> _Env:
    policy = _policy(
        not_before=datetime(2026, 11, 24, 14, 0, tzinfo=UTC),
        expires_at=datetime(2026, 11, 30, 21, 30, tzinfo=UTC),
        tracks=(_budget(track="DAY"),),
        strategies=(StrategyScope("native_orb", "test-v1", "DAY",
                                  "SD022.md", EVIDENCE_SHA,
                                  "etoro-demo:tradingagents"),),
    )
    env = _Env(tmp_path, policy)
    env.clock.now = when
    return env


def _day_entry(env: _Env) -> EntryProposal | Refusal:
    now = env.clock.now
    signal = ResearchSignal(
        canonical_id=MSFT, track="DAY", source_kind="NATIVE_STRATEGY",
        source_id="native_orb", source_version="test-v1",
        horizon_min_days=0, horizon_max_days=0, direction="LONG",
        evidence=(EvidenceRef("backtest", "SD022.md", SHA),),
        generated_at=now - timedelta(minutes=2),
        data_cutoff=now - timedelta(minutes=3),
        invalidation=("opening range invalidated",),
    )
    return env.rt.propose_entry(
        track="DAY", signals=(signal,),
        admissions=(StrategyAdmission("native_orb", "test-v1", "DAY", "ADMITTED",
                                      "SD022.md", 45, True),),
        market=env.market(), quote=env.quote(), marks={},
    )


def _filled_day_position(env: _Env) -> EntryProposal:
    proposal = _day_entry(env)
    assert isinstance(proposal, EntryProposal), proposal
    env.ledger.resolve(
        _fill(proposal.reference_id, "FILLED", env.clock.now,
              filled_units=proposal.units, avg_price=Decimal("500"),
              broker_position_id="500100"),
    )
    return proposal


@pytest.mark.parametrize("day", [date(2026, 11, 25), date(2026, 11, 27)])
def test_day_position_remains_open_until_10_min_before_actual_session_close(
    tmp_path: Path, day: date,
) -> None:
    session = session_for(day)
    assert session is not None
    if day.day == 27:
        assert session.early_close
    env = _day_env(tmp_path, session.open_utc + timedelta(minutes=30))
    try:
        entry = _filled_day_position(env)
        assert entry.horizon_max_days == 0
        assert env.rt.plan_exits(bids=env.bids("499")).exits == ()

        env.clock.now = session.close_utc - timedelta(minutes=11)
        assert env.rt.plan_exits(bids=env.bids("499")).exits == ()

        env.clock.now = session.close_utc - timedelta(minutes=10)
        plan = env.rt.plan_exits(bids=env.bids("499"))
        assert len(plan.exits) == 1
        assert plan.exits[0].reason == "DAY_SESSION_FLATTEN"
        assert plan.exits[0].entry_reference == entry.reference_id
        again = env.rt.plan_exits(bids=env.bids("499"))
        assert again.exits == ()
        assert again.alerts == (f"EXIT_PENDING:{entry.reference_id}",)
    finally:
        env.ledger.close()


@pytest.mark.parametrize("day", [date(2026, 11, 25), date(2026, 11, 27)])
def test_day_new_entry_is_refused_in_last_30_minutes(
    tmp_path: Path, day: date,
) -> None:
    session = session_for(day)
    assert session is not None
    env = _day_env(tmp_path, session.close_utc - timedelta(minutes=30))
    try:
        assert _day_entry(env) == Refusal(("DAY_ENTRY_WINDOW_CLOSED",))
        assert env.ledger.open_positions() == ()
    finally:
        env.ledger.close()


def test_missed_day_flatten_escalates_at_next_open(tmp_path: Path) -> None:
    original = session_for(date(2026, 11, 25))
    later = session_for(date(2026, 11, 27))
    assert original is not None and later is not None
    env = _day_env(tmp_path, original.open_utc + timedelta(minutes=30))
    try:
        entry = _filled_day_position(env)
        env.clock.now = later.open_utc + timedelta(minutes=5)
        plan = env.rt.plan_exits(bids=env.bids("499"))
        assert [e.reason for e in plan.exits] == ["DAY_OVERDUE_FLATTEN"]
        assert plan.exits[0].entry_reference == entry.reference_id
        assert f"DAY_OVERNIGHT_POSITION:{entry.reference_id}" in plan.alerts
    finally:
        env.ledger.close()


def test_unclosed_day_position_outside_session_is_visible_incident(tmp_path: Path) -> None:
    session = session_for(date(2026, 11, 25))
    assert session is not None
    env = _day_env(tmp_path, session.open_utc + timedelta(minutes=30))
    try:
        entry = _filled_day_position(env)
        env.clock.now = session.close_utc + timedelta(minutes=5)
        plan = env.rt.plan_exits(bids=env.bids("499"))
        assert plan.exits == ()
        assert f"DAY_POSITION_OUTSIDE_SESSION:{entry.reference_id}" in plan.alerts
        assert env.ledger.open_positions()  # never invent a closed position
    finally:
        env.ledger.close()


def test_day_protective_stop_precedes_session_flatten(tmp_path: Path) -> None:
    session = session_for(date(2026, 11, 27))
    assert session is not None
    env = _day_env(tmp_path, session.open_utc + timedelta(minutes=30))
    try:
        _filled_day_position(env)
        env.clock.now = session.close_utc - timedelta(minutes=10)
        plan = env.rt.plan_exits(bids=env.bids("470"))
        assert [e.reason for e in plan.exits] == ["STOP_BREACHED"]
    finally:
        env.ledger.close()
