"""Canonical digest validation is not a replacement for signed provenance."""
import pytest

from sidedeck.application.sd152_digest_integrity import validate_offline_digest
from sidedeck.application.sd152_offline_alert_digest import build_offline_alert_digest


def _digest():
    return build_offline_alert_digest({
        "schema": "sidedeck.sd152.offline-operator-alerts/1",
        "status": "ATTENTION_REQUIRED", "incidents": ["FENCE_UNRESOLVED"],
        "safe_to_trade": False, "automatic_recovery_allowed": False,
        "clear_halt_allowed": False, "execution_release": "ETORO_DEMO_NOT_RELEASED",
    })


def test_generated_incident_digest_matches_canonical_evidence():
    assert validate_offline_digest(_digest())


@pytest.mark.parametrize("change", [
    {"dedup_sha256": "a" * 64},
    {"incidents": ["ANOTHER_INCIDENT"]},
    {"incidents": ["FENCE_UNRESOLVED", "FENCE_UNRESOLVED"]},
    {"incidents": ["fence_unresolved"]},
    {"severity": "INFORMATIONAL"},
    {"operator_action": "NONE"},
    {"execution_release": "RELEASED"},
    {"safe_to_trade": True},
    {"delivery_status": "SENT"},
])
def test_altered_digest_is_not_admitted(change):
    assert not validate_offline_digest({**_digest(), **change})
