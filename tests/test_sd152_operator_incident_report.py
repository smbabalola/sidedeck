"""A locally acknowledged incident still needs external escalation and human review."""
from datetime import UTC, datetime

from sidedeck.application.sd152_offline_alert_digest import build_offline_alert_digest
from sidedeck.application.sd152_offline_alert_journal import OfflineAlertJournal
from sidedeck.application.sd152_operator_acknowledgement import OfflineOperatorAcknowledgements
from sidedeck.application.sd152_operator_incident_report import report_offline_incident


def test_acknowledgement_is_visible_but_never_resolves_or_delivers(tmp_path):
    digest = build_offline_alert_digest({
        "schema": "sidedeck.sd152.offline-operator-alerts/1",
        "status": "ATTENTION_REQUIRED", "incidents": ["FENCE_UNRESOLVED"],
        "safe_to_trade": False, "automatic_recovery_allowed": False,
        "clear_halt_allowed": False, "execution_release": "ETORO_DEMO_NOT_RELEASED",
    })
    at = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
    journal = OfflineAlertJournal(tmp_path / "alerts.sqlite3").record(digest, at=at)
    before = report_offline_incident(digest, journal)
    assert before["status"] == "ESCALATION_REQUIRED"
    assert not before["operator_acknowledged"]
    ack = OfflineOperatorAcknowledgements(tmp_path / "ack.sqlite3").acknowledge(
        digest, actor="operator-1", at=at)
    after = report_offline_incident(digest, journal, ack)
    assert after["operator_acknowledged"]
    assert after["status"] == "ESCALATION_REQUIRED"
    assert not after["incident_resolved"]
    assert not after["external_notification_confirmed"]
    assert not after["safe_to_trade"]
    restarted = OfflineOperatorAcknowledgements(tmp_path / "ack.sqlite3").acknowledge(
        digest, actor="operator-1", at=at)
    assert report_offline_incident(digest, journal, restarted)["operator_acknowledged"]
    forged = report_offline_incident(digest, journal, {**ack, "incident_resolved": True})
    assert not forged["operator_acknowledged"]
    assert "OPERATOR_ACKNOWLEDGEMENT_INVALID" in forged["incidents"]
    mismatched = report_offline_incident(digest, journal, {**ack, "digest": "0" * 64})
    assert not mismatched["operator_acknowledged"]
    assert "OPERATOR_ACKNOWLEDGEMENT_INVALID" in mismatched["incidents"]
