"""Multi-day restart and outage scheduling qualification, offline only."""
from datetime import UTC, date, datetime

from sidedeck.application.sd068_track_scheduler import (
    DEFAULT_JOBS, UK_DEFAULT_JOBS, SchedulerStore, session_for, slots_for,
)


def test_multiday_restart_swing_slots_are_not_replayed(tmp_path):
    db = tmp_path / "restart.sqlite3"
    job = next(j for j in DEFAULT_JOBS if j.job_id == "swing_review")
    store = SchedulerStore(db)
    store.set_track("SWING", enabled=True, mode="SIMULATION_ONLY")
    store.set_exchange_track("XNYS", "SWING", enabled=True, mode="SIMULATION_ONLY")
    day = date(2026, 10, 22)
    slot = slots_for(job, day)[1]
    now = slot
    first = store.claim(job.job_id, slot, "worker-one", now)
    assert first.claimed
    store.finish(job.job_id, slot, "worker-one", now, ok=True)
    for attempt in range(10):
        restarted = SchedulerStore(db)
        assert not restarted.claim(job.job_id, slot, f"restart-{attempt}", now).claimed
        assert restarted.effective_mode(job) == "SIMULATION_ONLY"
    assert len([r for r in store.history(job.job_id) if r[0] == slot.isoformat()]) == 1


def test_us_uk_swing_calendar_multi_day_separation():
    jobs = {j.job_id: j for j in (*DEFAULT_JOBS, *UK_DEFAULT_JOBS)}
    for day in (date(2026, 10, 22), date(2026, 10, 23),
                date(2026, 10, 26), date(2026, 10, 27),
                date(2026, 11, 26), date(2026, 11, 27)):
        us = session_for(day, "XNYS")
        uk = session_for(day, "XLON")
        if us is not None:
            assert slots_for(jobs["swing_review"], day)
        else:
            assert not slots_for(jobs["swing_review"], day)
        if uk is not None:
            assert slots_for(jobs["xlon.swing_review"], day)
        else:
            assert not slots_for(jobs["xlon.swing_review"], day)
        assert all(s.tzinfo == UTC for s in
                   slots_for(jobs["swing_review"], day) +
                   slots_for(jobs["xlon.swing_review"], day))
