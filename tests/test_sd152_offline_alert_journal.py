from datetime import UTC, datetime, timedelta

import pytest

from sidedeck.application.sd152_offline_alert_journal import OfflineAlertJournal
from sidedeck.application.sd152_offline_alert_digest import build_offline_alert_digest


def alert():
    return build_offline_alert_digest({
        "schema": "sidedeck.sd152.offline-operator-alerts/1",
        "status": "ATTENTION_REQUIRED", "incidents": ["FENCE_UNRESOLVED"],
        "safe_to_trade": False, "automatic_recovery_allowed": False,
        "clear_halt_allowed": False, "execution_release": "ETORO_DEMO_NOT_RELEASED",
    })


def test_restart_deduplicates_durable_alert(tmp_path):
    path = tmp_path / "alerts.sqlite3"
    now = datetime.now(UTC)
    first = OfflineAlertJournal(path).record(alert(), at=now)
    second = OfflineAlertJournal(path).record(alert(), at=now + timedelta(seconds=1))
    assert first["first_observation"] is True
    assert second["first_observation"] is False
    assert second["observations"] == 2
    assert second["delivery_status"] == "NOT_CONFIGURED"
    assert not second["safe_to_trade"]


def test_clock_regression_and_forged_release_refused(tmp_path):
    journal = OfflineAlertJournal(tmp_path / "alerts.sqlite3")
    now = datetime.now(UTC)
    journal.record(alert(), at=now)
    with pytest.raises(ValueError):
        journal.record(alert(), at=now - timedelta(seconds=1))
    with pytest.raises(ValueError):
        journal.record({**alert(), "execution_release": "RELEASED"}, at=now)


def test_informational_journal_rejects_forged_empty_digest(tmp_path):
    journal = OfflineAlertJournal(tmp_path / "informational.sqlite3")
    now = datetime.now(UTC)
    informational = build_offline_alert_digest({
        "schema": "sidedeck.sd152.offline-operator-alerts/1",
        "status": "OBSERVATION_ONLY", "incidents": [],
        "safe_to_trade": False, "automatic_recovery_allowed": False,
        "clear_halt_allowed": False, "execution_release": "ETORO_DEMO_NOT_RELEASED",
    })
    assert journal.record(informational, at=now)["first_observation"] is True
    for altered in (
        {"dedup_sha256": "a" * 64},
        {"incidents": ["FENCE_UNRESOLVED"]},
        {"operator_action": "MANUAL_REVIEW_ONLY"},
        {"severity": "ACTION_REQUIRED"},
    ):
        with pytest.raises(ValueError, match="integrity"):
            journal.record({**informational, **altered}, at=now)
