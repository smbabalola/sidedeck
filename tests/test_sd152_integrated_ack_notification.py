"""Offline integration: atomic acknowledgement does not suppress alert delivery escalation."""
from datetime import UTC, datetime

import pytest

from sidedeck.application.sd152_atomic_offline_ack import AtomicOfflineAcknowledgement
from sidedeck.application.sd152_offline_alert_digest import build_offline_alert_digest
from sidedeck.application.sd152_offline_alert_journal import OfflineAlertJournal
from sidedeck.application.sd152_offline_notification_outbox import OfflineNotificationOutbox
from sidedeck.application.sd152_operator_incident_report import report_offline_incident
from sidedeck.application.sd152_notification_transport import (
    DisabledNotificationTransport, NotificationDeliveryNotReleased,
)


def test_atomic_ack_outbox_and_disabled_transport_survive_restart(tmp_path):
    at = datetime(2026, 10, 28, 16, tzinfo=UTC)
    digest = build_offline_alert_digest({
        "schema": "sidedeck.sd152.offline-operator-alerts/1",
        "status": "ATTENTION_REQUIRED", "incidents": ["FENCE_UNRESOLVED"],
        "safe_to_trade": False, "automatic_recovery_allowed": False,
        "clear_halt_allowed": False, "execution_release": "ETORO_DEMO_NOT_RELEASED",
    })
    fingerprint = digest["dedup_sha256"]
    auth = {
        "schema": "sidedeck.sd152.operator-incident-authorization/1",
        "authorization_status": "OFFLINE_VERIFIER_ACCEPTED",
        "external_identity_verified": False,
        "incident_digest": fingerprint, "subject": "fixture-operator",
        "execution_release": "ETORO_DEMO_NOT_RELEASED",
        "safe_to_trade": False, "notification_dispatch_allowed": False,
    }
    journal = OfflineAlertJournal(tmp_path / "journal.db").record(digest, at=at)
    ack_store = tmp_path / "ack.db"
    outbox_store = tmp_path / "outbox.db"
    ack = AtomicOfflineAcknowledgement(ack_store).record(
        digest, auth, nonce="ack-nonce-20261028-0001", at=at)
    intent = OfflineNotificationOutbox(outbox_store).record(digest, at=at)
    result = report_offline_incident(digest, journal, ack, intent)
    assert result["operator_acknowledged"] is True
    assert result["operator_identity_verified"] is False
    assert result["notification_intent_recorded"] is True
    assert result["status"] == "ESCALATION_REQUIRED"
    assert result["incident_resolved"] is False
    assert result["external_notification_confirmed"] is False
    assert result["safe_to_trade"] is False
    with pytest.raises(NotificationDeliveryNotReleased):
        DisabledNotificationTransport().send(result, destination="nowhere@example.invalid")
    with pytest.raises(ValueError, match="already acknowledged"):
        AtomicOfflineAcknowledgement(ack_store).record(
            digest, auth, nonce="ack-nonce-20261028-0002", at=at)
    repeated_intent = OfflineNotificationOutbox(outbox_store).record(digest, at=at)
    assert repeated_intent["observations"] == 2
    restarted = report_offline_incident(digest, journal, ack, repeated_intent)
    assert restarted["status"] == "ESCALATION_REQUIRED"
    assert restarted["delivery_status"] == "NOT_CONFIGURED"
    assert restarted["clear_halt_allowed"] is False
