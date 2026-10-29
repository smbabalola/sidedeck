from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from sidedeck.application.sd068_track_scheduler import (
    DEFAULT_JOBS,
    Cadence,
    JobSpec,
    SchedulerError,
    SchedulerStore,
    session_for,
    slots_for,
)

JOBS = {j.job_id: j for j in DEFAULT_JOBS}


def test_sessions_follow_new_york_time_across_dst_and_holidays() -> None:
    before = session_for(date(2026, 3, 6))   # EST
    after = session_for(date(2026, 3, 9))    # EDT (US DST began 2026-03-08)
    assert before and before.open_utc == datetime(2026, 3, 6, 14, 30, tzinfo=UTC)
    assert after and after.open_utc == datetime(2026, 3, 9, 13, 30, tzinfo=UTC)
    # UK clocks change on 2026-03-29; the US session must not move with them.
    gap = session_for(date(2026, 3, 27))
    assert gap and gap.open_utc == datetime(2026, 3, 27, 13, 30, tzinfo=UTC)
    assert session_for(date(2026, 11, 26)) is None          # Thanksgiving
    assert session_for(date(2026, 10, 24)) is None          # Saturday
    early = session_for(date(2026, 11, 27))
    assert early and early.early_close
    assert early.close_utc == datetime(2026, 11, 27, 18, 0, tzinfo=UTC)
    with pytest.raises(SchedulerError, match="does not cover"):
        session_for(date(2027, 1, 4))


def test_default_cadences() -> None:
    day = date(2026, 10, 22)
    day_scan = slots_for(JOBS["day_candidate_scan"], day)
    assert day_scan[0] == datetime(2026, 10, 22, 13, 35, tzinfo=UTC)
    assert day_scan[-1] == datetime(2026, 10, 22, 19, 50, tzinfo=UTC)
    assert all((b - a) == timedelta(minutes=5) for a, b in zip(day_scan, day_scan[1:]))
    assert len(slots_for(JOBS["swing_review"], day)) == 3
    assert len(slots_for(JOBS["risk_monitor"], day)) == 391
    # Early close shortens intraday cadences.
    assert slots_for(JOBS["day_candidate_scan"], date(2026, 11, 27))[-1] == datetime(
        2026, 11, 27, 17, 50, tzinfo=UTC)
    # Weekly job runs on the last session of the ISO week (Good Friday week -> Thursday).
    assert slots_for(JOBS["position_weekly"], date(2026, 4, 2))
    assert not slots_for(JOBS["position_weekly"], date(2026, 4, 1))
    assert slots_for(JOBS["position_weekly"], date(2026, 10, 23))
    assert slots_for(JOBS["broad_scan"], date(2026, 10, 24)) == ()


def test_due_coalesces_missed_slots_and_skips_disabled(tmp_path: Path) -> None:
    store = SchedulerStore(tmp_path / "s.sqlite3")
    now = datetime(2026, 10, 22, 14, 2, 30, tzinfo=UTC)
    due = {r.job_id: r for r in store.due(now)}
    assert "broker_reconcile" not in due          # requires authorization; never planned
    assert due["day_candidate_scan"].slot == datetime(2026, 10, 22, 14, 0, tzinfo=UTC)
    # 76 never-run slots from the previous session plus 5 earlier today are coalesced.
    assert due["day_candidate_scan"].skipped_missed == 81
    statuses = [s for _, s, _ in store.history("day_candidate_scan")]
    assert statuses.count("SKIPPED_MISSED") == 81
    # Asking again does not duplicate work or re-skip.
    again = {r.job_id: r for r in store.due(now)}
    assert again["day_candidate_scan"].skipped_missed == 0
    store.set_track("DAY", enabled=False)
    assert "day_candidate_scan" not in {r.job_id for r in store.due(now)}


def test_claim_prevents_overlap_duplicates_and_survives_restart(tmp_path: Path) -> None:
    db = tmp_path / "s.sqlite3"
    store = SchedulerStore(db)
    slot = datetime(2026, 10, 22, 14, 0, tzinfo=UTC)
    assert store.claim("day_candidate_scan", slot, "w1", slot).reason == "CLAIMED"  # lease 240 s
    assert store.claim("day_candidate_scan", slot, "w2",
                       slot + timedelta(seconds=10)).reason == "OVERLAP_RUNNING"
    restarted = SchedulerStore(db)
    later = slot + timedelta(seconds=250)   # lease expired (crashed worker), still within 5 min
    assert restarted.claim("day_candidate_scan", slot, "w3", later).reason == "LEASE_TAKEOVER"
    with pytest.raises(SchedulerError):
        restarted.finish("day_candidate_scan", slot, "w1", later, ok=True)   # lost lease
    restarted.finish("day_candidate_scan", slot, "w3", later, ok=True)
    assert restarted.claim("day_candidate_scan", slot, "w4", later).reason == "ALREADY_COMPLETED"
    assert restarted.claim("day_candidate_scan", slot + timedelta(hours=1), "w4",
                           later).reason == "NOT_YET_DUE"


def test_expired_run_on_other_slot_is_abandoned_not_left_running(tmp_path: Path) -> None:
    store = SchedulerStore(tmp_path / "s.sqlite3")
    slot = datetime(2026, 10, 22, 14, 0, tzinfo=UTC)
    store.claim("day_candidate_scan", slot, "w1", slot)
    nxt = slot + timedelta(minutes=10)
    assert store.claim("day_candidate_scan", nxt, "w2", nxt).claimed
    assert dict((s, st) for s, st, _ in store.history("day_candidate_scan"))[
        slot.isoformat()] == "ABANDONED_LEASE_EXPIRED"


def test_tracks_default_research_only_and_execution_cannot_be_enabled(tmp_path: Path) -> None:
    store = SchedulerStore(tmp_path / "s.sqlite3")
    assert all(mode == "RESEARCH_ONLY" for _, mode in store.track_controls().values())
    store.set_track("SWING", enabled=True, mode="SIMULATION_ONLY")
    assert store.track_controls()["SWING"] == (True, "SIMULATION_ONLY")
    for mode in ("EXECUTION", "LIVE", "DEMO_EXECUTION"):
        with pytest.raises(SchedulerError, match="autonomous Demo policy"):
            store.set_track("DAY", enabled=True, mode=mode)
    with pytest.raises(SchedulerError):
        store.set_track("CRYPTO", enabled=True)


def test_invalid_specs_and_naive_times(tmp_path: Path) -> None:
    with pytest.raises(SchedulerError):
        Cadence()
    with pytest.raises(SchedulerError):
        Cadence(every_minutes=0)
    with pytest.raises(SchedulerError):
        Cadence(offsets=(("NOON", 0),))
    with pytest.raises(SchedulerError):
        JobSpec("x", "FOREX", "", Cadence(every_minutes=5))
    dup = JobSpec("x", "DAY", "", Cadence(every_minutes=5))
    with pytest.raises(SchedulerError):
        SchedulerStore(tmp_path / "d.sqlite3", (dup, dup))
    store = SchedulerStore(tmp_path / "s.sqlite3")
    with pytest.raises(SchedulerError):
        store.due(datetime(2026, 10, 22, 14))


def test_review_claim_respects_job_track_and_cadence_gates(tmp_path: Path) -> None:
    store = SchedulerStore(tmp_path / "s.sqlite3")
    slot = datetime(2026, 10, 22, 13, 10, tzinfo=UTC)     # broker_reconcile OPEN-20
    assert store.claim("broker_reconcile", slot, "w", slot).reason in (
        "JOB_DISABLED", "REQUIRES_AUTHORIZATION")
    store.set_track("DAY", enabled=False)
    day_slot = datetime(2026, 10, 22, 14, 0, tzinfo=UTC)
    assert store.claim("day_candidate_scan", day_slot, "w", day_slot).reason == "TRACK_DISABLED"
    store.set_track("DAY", enabled=True)
    off_grid = day_slot + timedelta(minutes=2)
    assert store.claim("day_candidate_scan", off_grid, "w",
                       off_grid).reason == "NOT_A_SCHEDULED_SLOT"
    weekend = datetime(2026, 10, 24, 14, 0, tzinfo=UTC)
    assert store.claim("day_candidate_scan", weekend, "w", weekend).reason == "NOT_A_SCHEDULED_SLOT"


def test_review_same_instant_in_other_timezone_is_the_same_slot(tmp_path: Path) -> None:
    from zoneinfo import ZoneInfo

    store = SchedulerStore(tmp_path / "s.sqlite3")
    slot = datetime(2026, 10, 22, 14, 0, tzinfo=UTC)
    store.claim("day_candidate_scan", slot, "w1", slot)
    store.finish("day_candidate_scan", slot, "w1", slot + timedelta(seconds=30), ok=True)
    ny = slot.astimezone(ZoneInfo("America/New_York"))
    assert store.claim("day_candidate_scan", ny, "w2",
                       ny + timedelta(seconds=40)).reason == "ALREADY_COMPLETED"


def test_review_no_stale_runs_after_close_or_outage(tmp_path: Path) -> None:
    store = SchedulerStore(tmp_path / "s.sqlite3")
    after_close = datetime(2026, 10, 22, 21, 45, tzinfo=UTC)
    due = {r.job_id for r in store.due(after_close)}
    assert "day_candidate_scan" not in due and "swing_review" not in due
    assert "risk_monitor" not in due
    assert {"performance_analysis", "position_daily"} <= due   # within their 60-minute window
    statuses = {st for _, st, _ in store.history("day_candidate_scan")}
    assert statuses == {"SKIPPED_MISSED"}
    slot = datetime(2026, 10, 22, 19, 45, tzinfo=UTC)
    assert store.claim("day_candidate_scan", slot, "w", after_close).reason in (
        "TOO_LATE", "ALREADY_SKIPPED_MISSED")


def test_review_incomplete_2021_calendar_is_not_covered(tmp_path: Path) -> None:
    with pytest.raises(SchedulerError, match="does not cover"):
        session_for(date(2021, 5, 31))   # Memorial Day 2021 is absent from the table


def test_review_hand_edited_mode_disables_track(tmp_path: Path) -> None:
    import sqlite3

    db = tmp_path / "s.sqlite3"
    store = SchedulerStore(db)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE tracks SET mode='LIVE' WHERE track='DAY'")
    assert store.track_controls()["DAY"] == (False, "INVALID_MODE_DISABLED")
    slot = datetime(2026, 10, 22, 14, 0, tzinfo=UTC)
    assert store.claim("day_candidate_scan", slot, "w", slot).reason == "TRACK_DISABLED"
