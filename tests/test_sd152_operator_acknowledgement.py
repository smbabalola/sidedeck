"""Operator acknowledgement is persistent, immutable and never a recovery grant."""
from datetime import UTC, datetime, timedelta

import pytest

from sidedeck.application.sd152_offline_alert_digest import build_offline_alert_digest
from sidedeck.application.sd152_operator_acknowledgement import (
    OfflineOperatorAcknowledgements,
)


def _critical():
    return build_offline_alert_digest({
        "schema": "sidedeck.sd152.offline-operator-alerts/1",
        "status": "ATTENTION_REQUIRED",
        "incidents": ["STALE_RUNNING_HEARTBEAT_RECONCILIATION_REQUIRED"],
        "safe_to_trade": False,
        "automatic_recovery_allowed": False,
        "clear_halt_allowed": False,
        "execution_release": "ETORO_DEMO_NOT_RELEASED",
    })


def test_operator_ack_is_idempotent_on_restart_and_does_not_resolve_incident(tmp_path):
    path = tmp_path / "operator.sqlite3"
    at = datetime(2026, 10, 28, 13, 0, tzinfo=UTC)
    alert = _critical()
    first = OfflineOperatorAcknowledgements(path).acknowledge(
        alert, actor="operator-1", at=at)
    second = OfflineOperatorAcknowledgements(path).acknowledge(
        alert, actor="operator-1", at=at)
    assert first["already_recorded"] is False
    assert second["already_recorded"] is True
    for record in (first, second):
        assert record["external_notification_confirmed"] is False
        assert record["incident_resolved"] is False
        assert record["clear_halt_allowed"] is False
        assert record["safe_to_trade"] is False
        assert record["execution_release"] == "ETORO_DEMO_NOT_RELEASED"


def test_operator_ack_forgery_or_reassignment_is_rejected(tmp_path):
    journal = OfflineOperatorAcknowledgements(tmp_path / "operator.sqlite3")
    at = datetime(2026, 10, 28, 13, 0, tzinfo=UTC)
    alert = _critical()
    journal.acknowledge(alert, actor="operator-1", at=at)
    with pytest.raises(ValueError, match="immutable"):
        journal.acknowledge(alert, actor="other-operator", at=at)
    with pytest.raises(ValueError, match="immutable"):
        journal.acknowledge(alert, actor="operator-1", at=at + timedelta(seconds=1))
    for forged in ({**alert, "execution_release": "RELEASED"},
                   {**alert, "delivery_status": "SENT"},
                   {**alert, "clear_halt_allowed": True}):
        with pytest.raises(ValueError):
            journal.acknowledge(forged, actor="operator-1", at=at)
    with pytest.raises(ValueError):
        journal.acknowledge(alert, actor="operator 1", at=at)
