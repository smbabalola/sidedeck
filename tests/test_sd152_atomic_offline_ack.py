"""Atomic offline acknowledgement and nonce reservation: restart, rollback, scope."""
from datetime import UTC, datetime

import pytest

from sidedeck.application.sd152_atomic_offline_ack import AtomicOfflineAcknowledgement
from sidedeck.application.sd152_offline_alert_digest import build_offline_alert_digest


def _digest(d):
    return build_offline_alert_digest({
        "schema": "sidedeck.sd152.offline-operator-alerts/1",
        "status": "ATTENTION_REQUIRED", "incidents": [f"INCIDENT_{d[0].upper()}"],
        "safe_to_trade": False, "automatic_recovery_allowed": False,
        "clear_halt_allowed": False, "execution_release": "ETORO_DEMO_NOT_RELEASED",
    })


def _auth(d):
    return dict(schema="sidedeck.sd152.operator-incident-authorization/1",
                authorization_status="OFFLINE_VERIFIER_ACCEPTED",
                external_identity_verified=False, incident_digest=d,
                subject="fixture-operator",
                execution_release="ETORO_DEMO_NOT_RELEASED",
                safe_to_trade=False, notification_dispatch_allowed=False)


def test_ack_and_nonce_are_atomic_and_survive_restart(tmp_path):
    path = tmp_path / "ack.sqlite3"
    at = datetime(2026, 10, 28, 16, tzinfo=UTC)
    nonce = "fixture-nonce-123456789"
    a = AtomicOfflineAcknowledgement(path)
    a_digest = _digest("a" * 64)
    b_digest = _digest("b" * 64)
    first = a.record(a_digest, _auth(a_digest["dedup_sha256"]), nonce=nonce, at=at)
    assert first["nonce_reserved"]
    assert first["external_identity_verified"] is False
    assert first["safe_to_trade"] is False
    restarted = AtomicOfflineAcknowledgement(path)
    with pytest.raises(ValueError, match="already acknowledged"):
        restarted.record(a_digest, _auth(a_digest["dedup_sha256"]), nonce="different-nonce-123456", at=at)
    with pytest.raises(ValueError, match="replayed nonce"):
        restarted.record(b_digest, _auth(b_digest["dedup_sha256"]), nonce=nonce, at=at)
    assert restarted.record(
        b_digest, _auth(b_digest["dedup_sha256"]),
        nonce="different-nonce-123456", at=at)["nonce_reserved"]


def test_rejected_mismatched_digest_does_not_consume_nonce(tmp_path):
    path = tmp_path / "ack.sqlite3"
    a = AtomicOfflineAcknowledgement(path)
    at = datetime(2026, 10, 28, 16, tzinfo=UTC)
    nonce = "fixture-nonce-123456789"
    digest = _digest("a" * 64)
    with pytest.raises(ValueError, match="evidence invalid"):
        a.record(digest, _auth("b" * 64), nonce=nonce, at=at)
    assert a.record(digest, _auth(digest["dedup_sha256"]), nonce=nonce, at=at)["nonce_reserved"]


def test_forged_digest_rejected_without_consuming_nonce(tmp_path):
    store = AtomicOfflineAcknowledgement(tmp_path / "ack.sqlite3")
    now = datetime(2026, 10, 28, 16, tzinfo=UTC)
    digest = _digest("a" * 64)
    nonce = "fixture-nonce-123456789"
    forged = {**digest, "dedup_sha256": "a" * 64}
    with pytest.raises(ValueError, match="evidence invalid"):
        store.record(forged, _auth(forged["dedup_sha256"]), nonce=nonce, at=now)
    assert store.record(digest, _auth(digest["dedup_sha256"]), nonce=nonce, at=now)["nonce_reserved"]
