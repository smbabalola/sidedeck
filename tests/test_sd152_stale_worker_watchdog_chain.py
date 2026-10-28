"""Offline stale-worker watchdog chain: fence read, digest, durable journal, escalation.

No broker, network, owner signing, notification send, or recovery action.
"""
from datetime import UTC, datetime, timedelta
import sqlite3

from sidedeck.application.sd152_offline_fence_readonly import readonly_fence_status
from sidedeck.application.sd152_offline_alert_digest import build_offline_alert_digest
from sidedeck.application.sd152_offline_alert_journal import OfflineAlertJournal
from sidedeck.application.sd152_offline_watchdog import assess_offline_watchdog


def test_stale_worker_across_observation_and_journal_restart(tmp_path):
    fence_db = tmp_path / "fence.sqlite3"
    journal_db = tmp_path / "alerts.sqlite3"
    start = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
    with sqlite3.connect(fence_db) as db:
        db.execute("CREATE TABLE offline_swing_single_writer "
                   "(id integer, state text, token text, slot text, updated_at text)")
        db.execute("CREATE TABLE offline_swing_runs "
                   "(slot text, token text, state text)")
        db.execute("INSERT INTO offline_swing_single_writer VALUES "
                   "(1,'RUNNING','owner-token','slot',?)", (start.isoformat(),))
        db.execute("INSERT INTO offline_swing_runs VALUES ('slot','owner-token','RUNNING')")
    original = fence_db.read_bytes()
    for i, offset in enumerate((121, 180, 240, 300)):
        result = readonly_fence_status(str(fence_db),
                                       now=start + timedelta(seconds=offset))
        assert "STALE_RUNNING_HEARTBEAT_RECONCILIATION_REQUIRED" in result["incidents"]
        # Convert untrusted fence observation to a digest through the existing
        # fail-closed operator alert schema; never claim to have read a broker.
        alert = {
            "schema": "sidedeck.sd152.offline-operator-alerts/1",
            "status": "ATTENTION_REQUIRED",
            "incidents": ["STALE_RUNNING_HEARTBEAT_RECONCILIATION_REQUIRED"],
            "safe_to_trade": False,
            "automatic_recovery_allowed": False,
            "clear_halt_allowed": False,
            "execution_release": "ETORO_DEMO_NOT_RELEASED",
        }
        digest = build_offline_alert_digest(alert)
        saved = OfflineAlertJournal(journal_db).record(
            digest, at=start + timedelta(seconds=offset))
        assert saved["observations"] == i + 1
        watch = assess_offline_watchdog(digest, saved)
        assert watch["status"] == "ESCALATION_REQUIRED"
        assert watch["external_notification_confirmed"] is False
        assert watch["safe_to_trade"] is False
    assert fence_db.read_bytes() == original
