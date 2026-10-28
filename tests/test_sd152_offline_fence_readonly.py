"""Read-only fence observation never becomes recovery permission."""
from datetime import UTC, datetime, timedelta
import sqlite3

from sidedeck.application.sd152_offline_fence_readonly import readonly_fence_status


def test_missing_path_does_not_create_database(tmp_path):
    path = tmp_path / "missing.sqlite3"
    result = readonly_fence_status(str(path), now=datetime.now(UTC))
    assert not path.exists()
    assert result["fence_state"] == "UNVERIFIED"
    assert result["automatic_post_allowed"] is False


def test_idle_valid_fence_remains_recovery_unverified(tmp_path):
    path = tmp_path / "fence.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE offline_swing_single_writer (id integer, state text, token text, slot text, updated_at text)")
        db.execute("INSERT INTO offline_swing_single_writer VALUES(1,'IDLE','','','')")
    original = path.read_bytes()
    result = readonly_fence_status(str(path), now=datetime.now(UTC))
    assert result["fence_state"] == "IDLE"
    assert result["status"] == "ACTION_REQUIRED"
    assert "RECOVERY_EVIDENCE_UNAVAILABLE" in result["incidents"]
    assert path.read_bytes() == original


def test_stale_running_fence_reports_incident_without_takeover(tmp_path):
    path = tmp_path / "fence.sqlite3"
    now = datetime.now(UTC)
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE offline_swing_single_writer (id integer, state text, token text, slot text, updated_at text)")
        db.execute("CREATE TABLE offline_swing_runs (slot text, token text, state text)")
        db.execute("INSERT INTO offline_swing_single_writer VALUES (1,?,?,?,?)",
                   ("RUNNING", "token", "slot", (now-timedelta(minutes=3)).isoformat()))
        db.execute("INSERT INTO offline_swing_runs VALUES ('slot','token','RUNNING')")
    result = readonly_fence_status(str(path), now=now)
    assert result["fence_state"] == "RUNNING"
    assert "STALE_RUNNING_HEARTBEAT_RECONCILIATION_REQUIRED" in result["incidents"]
    assert result["clear_halt_allowed"] is False


def test_corrupt_fence_and_symlink_are_unverified(tmp_path):
    bad = tmp_path / "bad.sqlite3"
    bad.write_text("not a database")
    link = tmp_path / "alias.sqlite3"
    link.symlink_to(bad)
    for path in (bad, link):
        result = readonly_fence_status(str(path), now=datetime.now(UTC))
        assert "OFFLINE_FENCE_EVIDENCE_INVALID" in result["incidents"]
        assert result["fence_state"] == "UNVERIFIED"
