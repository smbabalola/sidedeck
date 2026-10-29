"""Offline watchdog never implies delivered alerts or released trading."""
from datetime import UTC, datetime

from sidedeck.application.sd152_offline_alert_digest import build_offline_alert_digest
from sidedeck.application.sd152_offline_alert_journal import OfflineAlertJournal
from sidedeck.application.sd152_offline_watchdog import assess_offline_watchdog


def _digest(incidents):
    return build_offline_alert_digest({
        "schema": "sidedeck.sd152.offline-operator-alerts/1",
        "status": "ATTENTION_REQUIRED" if incidents else "OBSERVATION_ONLY",
        "incidents": incidents,
        "safe_to_trade": False,
        "automatic_recovery_allowed": False,
        "clear_halt_allowed": False,
        "execution_release": "ETORO_DEMO_NOT_RELEASED",
    })


def test_critical_incident_escalates_across_local_journal_restart(tmp_path):
    path = tmp_path / "alerts.sqlite3"
    digest = _digest(["FENCE_UNRESOLVED"])
    first = OfflineAlertJournal(path).record(digest, at=datetime.now(UTC))
    report = assess_offline_watchdog(digest, first)
    assert report["status"] == "ESCALATION_REQUIRED"
    assert report["incidents"] == ["OPERATOR_ACKNOWLEDGEMENT_AND_DELIVERY_NOT_CONFIGURED"]
    assert report["external_notification_confirmed"] is False
    assert report["safe_to_trade"] is False
    again = OfflineAlertJournal(path).record(digest, at=datetime.now(UTC))
    assert again["observations"] == 2
    assert assess_offline_watchdog(digest, again) == report


def test_clean_local_observation_is_not_broker_release(tmp_path):
    digest = _digest([])
    record = OfflineAlertJournal(tmp_path / "alerts.sqlite3").record(digest, at=datetime.now(UTC))
    report = assess_offline_watchdog(digest, record)
    assert report["status"] == "OBSERVATION_ONLY"
    assert report["delivery_status"] == "NOT_CONFIGURED"
    assert report["execution_release"] == "ETORO_DEMO_NOT_RELEASED"


def test_missing_or_forged_local_evidence_escalates(tmp_path):
    digest = _digest(["FENCE_UNRESOLVED"])
    record = OfflineAlertJournal(tmp_path / "alerts.sqlite3").record(digest, at=datetime.now(UTC))
    for invalid in (None, {}, {**record, "delivery_status": "SENT"},
                    {**record, "observations": True},
                    {**record, "execution_release": "RELEASED"}):
        report = assess_offline_watchdog(digest, invalid)
        assert report["incidents"] == ["WATCHDOG_EVIDENCE_INVALID"]
        assert report["status"] == "ESCALATION_REQUIRED"
    forged = assess_offline_watchdog({**digest, "safe_to_trade": True}, record)
    assert forged["incidents"] == ["WATCHDOG_EVIDENCE_INVALID"]
