"""Bundle O multi-exchange scheduling and fail-closed track isolation tests.

Planning only. No broker transport, owner release, or daemon.
"""
from datetime import UTC, date, datetime

from sidedeck.application.sd068_track_scheduler import (
    DEFAULT_JOBS, UK_DEFAULT_JOBS, SchedulerStore, session_for, slots_for,
)


def test_us_uk_different_dst_weeks_and_market_holidays():
    jobs = {j.job_id: j for j in (*DEFAULT_JOBS, *UK_DEFAULT_JOBS)}
    for day in (date(2026, 3, 27), date(2026, 3, 30), date(2026, 10, 23), date(2026, 10, 26)):
        us = session_for(day, "XNYS")
        uk = session_for(day, "XLON")
        assert us is not None and uk is not None
        assert us.open_utc != uk.open_utc
        us_slots = slots_for(jobs["swing_review"], day)
        uk_slots = slots_for(jobs["xlon.swing_review"], day)
        assert us_slots and uk_slots
        assert all(slot.tzinfo == UTC for slot in us_slots + uk_slots)
    # US Thanksgiving is a normal UK session; UK early May bank holiday is US trading.
    assert session_for(date(2026, 11, 26), "XNYS") is None
    assert session_for(date(2026, 11, 26), "XLON") is not None
    assert session_for(date(2026, 5, 4), "XLON") is None
    assert session_for(date(2026, 5, 4), "XNYS") is not None


def test_exchange_track_controls_survive_restart_without_enabling_uk_day(tmp_path):
    db = tmp_path / "calendar-tracks.sqlite3"
    jobs = DEFAULT_JOBS + UK_DEFAULT_JOBS
    store = SchedulerStore(db, jobs=jobs)
    store.set_track("SWING", enabled=True, mode="SIMULATION_ONLY")
    store.set_exchange_track("XNYS", "SWING", enabled=True, mode="SIMULATION_ONLY")
    store.set_exchange_track("XLON", "SWING", enabled=False, mode="RESEARCH_ONLY")
    restarted = SchedulerStore(db, jobs=jobs)
    assert restarted.effective_mode(restarted.jobs["swing_review"]) == "SIMULATION_ONLY"
    assert restarted.effective_mode(restarted.jobs["xlon.swing_review"]) == "RESEARCH_ONLY"
    assert restarted.jobs["xlon.day_candidate_scan"].enabled is False
    assert restarted.jobs["broker_reconcile"].requires_authorization is True
    assert restarted.jobs["broker_reconcile"].enabled is False
    restarted.set_exchange_track("XLON", "SWING", enabled=True, mode="SIMULATION_ONLY")
    restarted.set_track("SWING", enabled=False, mode="RESEARCH_ONLY")
    assert restarted.effective_mode(restarted.jobs["swing_review"]) == "RESEARCH_ONLY"
    assert restarted.effective_mode(restarted.jobs["xlon.swing_review"]) == "RESEARCH_ONLY"
