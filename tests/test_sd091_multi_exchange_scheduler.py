from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from sidedeck.application.sd068_track_scheduler import (
    DEFAULT_JOBS,
    MULTI_EXCHANGE_JOBS,
    UK_DEFAULT_JOBS,
    Cadence,
    JobSpec,
    SchedulerError,
    SchedulerStore,
    session_for,
    slots_for,
)

UK = {j.job_id: j for j in UK_DEFAULT_JOBS}
US = {j.job_id: j for j in DEFAULT_JOBS}


def _utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


def test_uk_slots_use_london_sessions_across_dst() -> None:
    assert slots_for(UK["xlon.swing_review"], date(2026, 10, 23)) == (
        _utc(2026, 10, 23, 6, 30), _utc(2026, 10, 23, 11, 0), _utc(2026, 10, 23, 15, 0))
    assert slots_for(UK["xlon.swing_review"], date(2026, 10, 26)) == (
        _utc(2026, 10, 26, 7, 30), _utc(2026, 10, 26, 12, 0), _utc(2026, 10, 26, 16, 0))
    assert slots_for(UK["xlon.position_daily"], date(2026, 12, 24)) == (
        _utc(2026, 12, 24, 13, 30),)  # half day: 12:30 close + 60 min
    assert session_for(date(2026, 10, 23), "XLON").open_utc == _utc(2026, 10, 23, 7)  # type: ignore[union-attr]


def test_holidays_do_not_leak_between_exchanges() -> None:
    assert slots_for(UK["xlon.swing_review"], date(2026, 8, 31)) == ()   # UK bank holiday
    assert slots_for(US["swing_review"], date(2026, 8, 31))
    assert slots_for(UK["xlon.swing_review"], date(2026, 11, 26))        # US Thanksgiving
    assert slots_for(US["swing_review"], date(2026, 11, 26)) == ()
    assert slots_for(UK["xlon.position_weekly"], date(2026, 10, 23))      # Friday
    assert not slots_for(UK["xlon.position_weekly"], date(2026, 10, 22))


def test_job_ids_must_be_namespaced_per_exchange() -> None:
    with pytest.raises(SchedulerError, match="namespaced"):
        JobSpec("swing_review", "SWING", "x", Cadence(offsets=(("OPEN", 0),)), calendar_id="XLON")
    with pytest.raises(SchedulerError, match="unknown exchange calendar"):
        JobSpec("xetr.scan", "SWING", "x", Cadence(offsets=(("OPEN", 0),)), calendar_id="XETR")
    assert len({j.job_id for j in MULTI_EXCHANGE_JOBS}) == len(MULTI_EXCHANGE_JOBS)


def test_us_and_uk_jobs_run_independently_without_duplicates(tmp_path: Path) -> None:
    store = SchedulerStore(tmp_path / "s.sqlite3", MULTI_EXCHANGE_JOBS)
    due = {r.job_id for r in store.due(_utc(2026, 10, 23, 6, 31))}
    assert "xlon.swing_review" in due and "swing_review" not in due
    uk_slot, us_slot = _utc(2026, 10, 23, 15, 0), _utc(2026, 10, 23, 15, 0)
    assert store.claim("xlon.swing_review", uk_slot, "w1", _utc(2026, 10, 23, 15, 1)).claimed
    assert store.claim("xlon.swing_review", uk_slot, "w2", _utc(2026, 10, 23, 15, 2)).reason == \
        "OVERLAP_RUNNING"
    store.finish("xlon.swing_review", uk_slot, "w1", _utc(2026, 10, 23, 15, 3), ok=True)
    assert store.claim("xlon.swing_review", uk_slot, "w3", _utc(2026, 10, 23, 15, 4)).reason == \
        "ALREADY_COMPLETED"
    # A US job at the same instant is a different slot namespace and is not blocked.
    assert store.claim("risk_monitor", us_slot, "w4", _utc(2026, 10, 23, 15, 0, 30)).claimed


def test_per_exchange_track_controls(tmp_path: Path) -> None:
    store = SchedulerStore(tmp_path / "s.sqlite3", MULTI_EXCHANGE_JOBS)
    store.set_exchange_track("XLON", "SWING", enabled=False)
    assert store.claim("xlon.swing_review", _utc(2026, 10, 23, 11), "w",
                       _utc(2026, 10, 23, 11, 1)).reason == "EXCHANGE_TRACK_DISABLED"
    assert store.claim("swing_review", _utc(2026, 10, 23, 13), "w",
                       _utc(2026, 10, 23, 13, 1)).claimed
    assert store.claim("xlon.day_candidate_scan", _utc(2026, 10, 23, 7, 5), "w",
                       _utc(2026, 10, 23, 7, 6)).reason == "JOB_DISABLED"
    assert store.claim("xlon.broker_reconcile", _utc(2026, 10, 23, 6, 40), "w",
                       _utc(2026, 10, 23, 6, 41)).reason == "JOB_DISABLED"
    with pytest.raises(SchedulerError):
        store.set_exchange_track("XLON", "SWING", enabled=True, mode="AUTONOMOUS_EXECUTION")
    controls = store.exchange_track_controls()
    assert controls[("XLON", "SWING")] == (False, "RESEARCH_ONLY")
    assert controls[("XNYS", "SWING")] == (True, "RESEARCH_ONLY")


def test_existing_store_upgrades_and_reopens(tmp_path: Path) -> None:
    path = tmp_path / "s.sqlite3"
    SchedulerStore(path, DEFAULT_JOBS)                       # pre-UK database
    store = SchedulerStore(path, MULTI_EXCHANGE_JOBS)        # adds XLON controls in place
    assert ("XLON", "POSITION") in store.exchange_track_controls()
    assert store.claim("xlon.position_daily", _utc(2026, 10, 23, 16, 30), "w",
                       _utc(2026, 10, 23, 16, 31)).claimed
