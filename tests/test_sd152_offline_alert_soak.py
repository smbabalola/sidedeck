"""Deterministic offline incident-journal soak; no external delivery or broker route."""
from datetime import UTC, datetime, timedelta
import sqlite3

import pytest

from sidedeck.application.sd152_offline_alert_digest import build_offline_alert_digest
from sidedeck.application.sd152_offline_alert_journal import OfflineAlertJournal


def digest(incident: str):
    return build_offline_alert_digest({
        "schema": "sidedeck.sd152.offline-operator-alerts/1",
        "status": "ATTENTION_REQUIRED", "incidents": [incident],
        "safe_to_trade": False, "automatic_recovery_allowed": False,
        "clear_halt_allowed": False, "execution_release": "ETORO_DEMO_NOT_RELEASED",
    })


def test_multiple_sessions_restart_preserves_dedup_and_separate_incidents(tmp_path):
    path = tmp_path / "alerts.sqlite3"
    start = datetime(2026, 10, 26, 12, tzinfo=UTC)
    for session in range(20):
        # Reconstruct reader/writer each session to simulate process restarts.
        journal = OfflineAlertJournal(path)
        first = journal.record(
            digest("STALE_RUNNING_HEARTBEAT_RECONCILIATION_REQUIRED"),
            at=start + timedelta(hours=session),
        )
        assert first["first_observation"] is (session == 0)
        assert first["observations"] == session + 1
        assert first["delivery_status"] == "NOT_CONFIGURED"
        assert first["clear_halt_allowed"] is False
        if session % 4 == 0:
            other = journal.record(digest("FENCE_UNRESOLVED"),
                                   at=start + timedelta(hours=session))
            assert not other["safe_to_trade"]
    with sqlite3.connect(path) as conn:
        rows = conn.execute("SELECT severity,observations FROM offline_alert_journal ORDER BY observations").fetchall()
    assert rows == [("ACTION_REQUIRED", 5), ("ACTION_REQUIRED", 20)]


def test_failed_or_forged_digest_never_advances_journal(tmp_path):
    path = tmp_path / "alerts.sqlite3"
    journal = OfflineAlertJournal(path)
    now = datetime(2026, 10, 28, tzinfo=UTC)
    report = digest("FENCE_UNRESOLVED")
    journal.record(report, at=now)
    for bad in [
        {**report, "safe_to_trade": True},
        {**report, "delivery_status": "SENT"},
        {**report, "dedup_sha256": "not-a-digest"},
    ]:
        with pytest.raises(ValueError):
            journal.record(bad, at=now + timedelta(seconds=1))
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT observations FROM offline_alert_journal").fetchone() == (1,)
