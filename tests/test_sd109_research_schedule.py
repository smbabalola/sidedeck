"""SD-109 scheduled research runs: SD-068 slots + run history, with a fake pipeline runner."""
from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from sidedeck.application import sd109_research_schedule as s
from sidedeck.application.sd068_track_scheduler import SchedulerStore

# Fri 2026-10-23 XNYS close 16:00 EDT = 20:00 UTC -> slot 20:45 UTC
CLOSE = datetime(2026, 10, 23, 20, 0, tzinfo=UTC)


def _rig(tmp_path: Path, latest: str = "2026-10-23", fail: bool = False):
    calls: list[int] = []

    def runner():
        calls.append(1)
        if fail:
            raise RuntimeError("market data refused")
        report = tmp_path / f"report-{len(calls)}.json"
        report.write_text("{}", encoding="utf-8")
        return ({"data_freshness": {"latest_session": latest},
                 "decisions": [{"decision": "ABSTAIN"}, {"decision": "WATCHLIST"}],
                 "orders": [], "no_trade": "NO TRADE: test"}, report)

    store = SchedulerStore(tmp_path / "sched.sqlite3", jobs=(s.JOB,))
    history = s.RunHistory(tmp_path / "hist.sqlite3")
    return store, history, runner, calls


def test_not_due_before_the_post_close_slot(tmp_path):
    store, history, runner, calls = _rig(tmp_path)
    out = s.tick(now=CLOSE + timedelta(minutes=30), store=store, history=history, runner=runner)
    assert out["status"] == "NOT_DUE" and calls == []
    assert out["next_slot"].startswith("2026-10-23T20:45")


def test_runs_once_per_session_and_records_evidence(tmp_path):
    store, history, runner, calls = _rig(tmp_path)
    first = s.tick(now=CLOSE + timedelta(minutes=50), store=store, history=history,
                   runner=runner)
    assert first["status"] == "COMPLETED" and first["freshness"] == "CURRENT"
    again = s.tick(now=CLOSE + timedelta(minutes=55), store=store, history=history,
                   runner=runner)
    assert again["status"] == "NOT_DUE" and len(calls) == 1
    row = history.rows()[0]
    assert row["session"] == "2026-10-23" and row["orders"] == 0
    assert row["report_sha256"] and len(row["report_sha256"]) == 64
    assert '"WATCHLIST": 1' in row["decisions"]


def test_stale_data_is_recorded_not_hidden(tmp_path):
    store, history, runner, _ = _rig(tmp_path, latest="2026-10-20")
    out = s.tick(now=CLOSE + timedelta(minutes=50), store=store, history=history, runner=runner)
    assert out["status"] == "STALE_DATA" and out["freshness"] == "STALE_3_SESSIONS"


def test_failures_are_recorded(tmp_path):
    store, history, runner, _ = _rig(tmp_path, fail=True)
    out = s.tick(now=CLOSE + timedelta(minutes=50), store=store, history=history, runner=runner)
    assert out["status"] == "FAILED" and "market data refused" in out["reason"]


def test_missed_close_still_runs_next_morning_once(tmp_path):
    store, history, runner, calls = _rig(tmp_path)
    morning = datetime(2026, 10, 24, 12, tzinfo=UTC)          # Saturday, within 18 h
    assert s.tick(now=morning, store=store, history=history,
                  runner=runner)["status"] == "COMPLETED"
    assert len(calls) == 1


def test_history_is_append_only(tmp_path):
    store, history, runner, _ = _rig(tmp_path)
    s.tick(now=CLOSE + timedelta(minutes=50), store=store, history=history, runner=runner)
    with sqlite3.connect(tmp_path / "hist.sqlite3") as conn, pytest.raises(sqlite3.DatabaseError):
        conn.execute("UPDATE sd109_runs SET status='COMPLETED'")


def test_freshness_labels():
    assert s.freshness(None, date(2026, 10, 23)) == "NO_DATA"
    assert s.freshness(date(2026, 10, 26), date(2026, 10, 23)) == "FUTURE_BAR_REFUSED"
    assert s.freshness(date(2026, 10, 22), date(2026, 10, 23)) == "STALE_1_SESSIONS"


def test_history_summary_is_read_only_and_bounded(tmp_path):
    assert s.history_summary(str(tmp_path / "none.sqlite3"))["status"] == "NOT_STARTED"
    store, history, runner, _ = _rig(tmp_path)
    s.tick(now=CLOSE + timedelta(minutes=50), store=store, history=history, runner=runner)
    summary = s.history_summary(str(tmp_path / "hist.sqlite3"))
    assert summary["execution_enabled"] is False and summary["status"] == "ACTIVE"
    assert summary["runs"][0]["decisions"] == {"ABSTAIN": 1, "WATCHLIST": 1}


def test_naive_time_refused(tmp_path):
    store, history, runner, _ = _rig(tmp_path)
    with pytest.raises(s.ScheduleError):
        s.tick(now=datetime(2026, 10, 23, 21), store=store, history=history, runner=runner)


def test_failed_run_marks_the_scheduler_slot_failed(tmp_path):
    store, history, runner, _ = _rig(tmp_path, fail=True)
    out = s.tick(now=CLOSE + timedelta(minutes=50), store=store, history=history, runner=runner)
    statuses = {status for _slot, status, _a in store.history(s.JOB_ID)}
    assert out["status"] == "FAILED" and "FAILED" in statuses


def test_future_bar_is_a_failure_not_stale(tmp_path):
    store, history, runner, _ = _rig(tmp_path, latest="2026-10-26")
    out = s.tick(now=CLOSE + timedelta(minutes=50), store=store, history=history, runner=runner)
    assert out["status"] == "FAILED" and out["freshness"] == "FUTURE_BAR_REFUSED"


def test_concurrent_claim_is_refused(tmp_path):
    store, history, runner, calls = _rig(tmp_path)
    due = [d for d in store.due(CLOSE + timedelta(minutes=50)) if d.job_id == s.JOB_ID][0]
    assert store.claim(s.JOB_ID, due.slot, "other-worker", CLOSE + timedelta(minutes=50)).claimed
    out = s.tick(now=CLOSE + timedelta(minutes=51), store=store, history=history, runner=runner)
    assert out["status"] in ("NOT_DUE", "NOT_CLAIMED") and calls == []


def test_interrupt_is_recorded_and_finishes_the_slot(tmp_path):
    store, history, _, _ = _rig(tmp_path)

    def interrupted():
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        s.tick(now=CLOSE + timedelta(minutes=50), store=store, history=history,
               runner=interrupted)
    assert history.rows()[0]["status"] == "FAILED"
    assert "FAILED" in {status for _slot, status, _a in store.history(s.JOB_ID)}


def test_history_summary_never_writes(tmp_path):
    other = tmp_path / "unrelated.sqlite3"
    sqlite3.connect(other).close()
    assert s.history_summary(str(other))["status"] == "UNAVAILABLE"
    with sqlite3.connect(other) as conn:
        assert conn.execute("SELECT count(*) FROM sqlite_master").fetchone()[0] == 0
