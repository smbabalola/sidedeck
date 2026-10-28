"""All three durable incident stores reject internally inconsistent alert digests."""
from datetime import UTC, datetime

import pytest

from sidedeck.application.sd152_offline_alert_digest import build_offline_alert_digest
from sidedeck.application.sd152_offline_alert_journal import OfflineAlertJournal
from sidedeck.application.sd152_offline_notification_outbox import OfflineNotificationOutbox
from sidedeck.application.sd152_operator_acknowledgement import OfflineOperatorAcknowledgements


def _critical():
    return build_offline_alert_digest({
        "schema": "sidedeck.sd152.offline-operator-alerts/1",
        "status": "ATTENTION_REQUIRED", "incidents": ["FENCE_UNRESOLVED"],
        "safe_to_trade": False, "automatic_recovery_allowed": False,
        "clear_halt_allowed": False, "execution_release": "ETORO_DEMO_NOT_RELEASED",
    })


@pytest.mark.parametrize("mutation", [
    {"dedup_sha256": "a" * 64},
    {"incidents": ["OTHER_INCIDENT"]},
    {"incidents": ["FENCE_UNRESOLVED", "FENCE_UNRESOLVED"]},
    {"operator_action": "NONE"},
])
def test_each_persistent_store_rejects_forged_critical_digest(tmp_path, mutation):
    alert = {**_critical(), **mutation}
    now = datetime(2026, 10, 28, 16, tzinfo=UTC)
    with pytest.raises(ValueError, match="integrity"):
        OfflineAlertJournal(tmp_path / "journal.sqlite3").record(alert, at=now)
    with pytest.raises(ValueError, match="integrity"):
        OfflineNotificationOutbox(tmp_path / "outbox.sqlite3").record(alert, at=now)
    with pytest.raises(ValueError, match="integrity"):
        OfflineOperatorAcknowledgements(tmp_path / "ack.sqlite3").acknowledge(
            alert, actor="operator-1", at=now)
