"""Atomic offline acknowledgement and nonce reservation: restart, rollback, scope."""
from datetime import UTC, datetime

import pytest

from sidedeck.application.sd152_atomic_offline_ack import AtomicOfflineAcknowledgement


def _digest(d):
    return dict(schema="sidedeck.sd152.offline-alert-digest/1",
                severity="ACTION_REQUIRED", dedup_sha256=d,
                delivery_status="NOT_CONFIGURED",
                execution_release="ETORO_DEMO_NOT_RELEASED",
                safe_to_trade=False, clear_halt_allowed=False)


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
    first = a.record(_digest("a" * 64), _auth("a" * 64), nonce=nonce, at=at)
    assert first["nonce_reserved"]
    assert first["external_identity_verified"] is False
    assert first["safe_to_trade"] is False
    restarted = AtomicOfflineAcknowledgement(path)
    with pytest.raises(ValueError, match="already acknowledged"):
        restarted.record(_digest("a" * 64), _auth("a" * 64), nonce="different-nonce-123456", at=at)
    with pytest.raises(ValueError, match="replayed nonce"):
        restarted.record(_digest("b" * 64), _auth("b" * 64), nonce=nonce, at=at)
    assert restarted.record(
        _digest("b" * 64), _auth("b" * 64),
        nonce="different-nonce-123456", at=at)["nonce_reserved"]


def test_rejected_mismatched_digest_does_not_consume_nonce(tmp_path):
    path = tmp_path / "ack.sqlite3"
    a = AtomicOfflineAcknowledgement(path)
    at = datetime(2026, 10, 28, 16, tzinfo=UTC)
    nonce = "fixture-nonce-123456789"
    with pytest.raises(ValueError, match="evidence invalid"):
        a.record(_digest("a" * 64), _auth("b" * 64), nonce=nonce, at=at)
    assert a.record(_digest("a" * 64), _auth("a" * 64), nonce=nonce, at=at)["nonce_reserved"]
