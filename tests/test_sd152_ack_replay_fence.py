"""Offline acknowledgement nonces are single-use even after restart."""
from datetime import UTC, datetime

import pytest

from sidedeck.application.sd152_ack_replay_fence import OfflineAcknowledgementReplayFence


def _authorization():
    return {
        "schema": "sidedeck.sd152.operator-incident-authorization/1",
        "authorization_status": "OFFLINE_VERIFIER_ACCEPTED",
        "external_identity_verified": False,
        "incident_digest": "a" * 64,
        "subject": "fixture-operator",
        "execution_release": "ETORO_DEMO_NOT_RELEASED",
        "safe_to_trade": False,
        "notification_dispatch_allowed": False,
    }


def test_nonce_refuses_reuse_after_restart(tmp_path):
    path = tmp_path / "ack-nonces.sqlite3"
    nonce = "fixture-nonce-123456789"
    at = datetime(2026, 10, 28, 14, tzinfo=UTC)
    first = OfflineAcknowledgementReplayFence(path).reserve(_authorization(), nonce=nonce, at=at)
    assert first["nonce_reserved"] is True
    assert first["external_identity_verified"] is False
    assert first["safe_to_trade"] is False
    with pytest.raises(ValueError, match="replayed"):
        OfflineAcknowledgementReplayFence(path).reserve(_authorization(), nonce=nonce, at=at)
    assert OfflineAcknowledgementReplayFence(path).reserve(
        _authorization(), nonce="fixture-nonce-987654321", at=at)["nonce_reserved"]


def test_forged_release_and_identity_claims_are_rejected(tmp_path):
    fence = OfflineAcknowledgementReplayFence(tmp_path / "ack-nonces.sqlite3")
    at = datetime(2026, 10, 28, 14, tzinfo=UTC)
    for forged in (
        {**_authorization(), "external_identity_verified": True},
        {**_authorization(), "execution_release": "RELEASED"},
        {**_authorization(), "notification_dispatch_allowed": True},
    ):
        with pytest.raises(ValueError):
            fence.reserve(forged, nonce="fixture-nonce-123456789", at=at)
