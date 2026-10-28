"""Notification intent outbox stays undelivered through restart and forgery."""
from datetime import UTC, datetime, timedelta

import pytest

from sidedeck.application.sd152_offline_alert_digest import build_offline_alert_digest
from sidedeck.application.sd152_offline_notification_outbox import OfflineNotificationOutbox


def _critical():
    return build_offline_alert_digest({
        "schema": "sidedeck.sd152.offline-operator-alerts/1",
        "status": "ATTENTION_REQUIRED",
        "incidents": ["FENCE_UNRESOLVED"],
        "safe_to_trade": False, "automatic_recovery_allowed": False,
        "clear_halt_allowed": False, "execution_release": "ETORO_DEMO_NOT_RELEASED",
    })


def test_notification_intent_survives_ten_restarts_without_claiming_delivery(tmp_path):
    path = tmp_path / "notifications.sqlite3"
    base = datetime(2026, 10, 28, 14, tzinfo=UTC)
    report = _critical()
    for attempt in range(10):
        state = OfflineNotificationOutbox(path).record(
            report, at=base + timedelta(seconds=attempt))
        assert state["observations"] == attempt + 1
        assert state["first_observation"] is (attempt == 0)
        assert state["delivery_status"] == "NOT_CONFIGURED"
        assert state["external_notification_confirmed"] is False
        assert state["dispatch_allowed"] is False
        assert state["safe_to_trade"] is False


def test_outbox_rejects_forged_release_and_backwards_clock(tmp_path):
    outbox = OfflineNotificationOutbox(tmp_path / "notifications.sqlite3")
    now = datetime(2026, 10, 28, 14, tzinfo=UTC)
    report = _critical()
    outbox.record(report, at=now)
    for forged in ({**report, "execution_release": "RELEASED"},
                   {**report, "delivery_status": "SENT"},
                   {**report, "safe_to_trade": True}):
        with pytest.raises(ValueError):
            outbox.record(forged, at=now)
    with pytest.raises(ValueError, match="clock regression"):
        outbox.record(report, at=now - timedelta(seconds=1))
