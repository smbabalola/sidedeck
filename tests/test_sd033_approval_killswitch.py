from datetime import datetime, timedelta, timezone

import pytest

from sidedeck.application.sd033_approval_killswitch import ApprovalError, ApprovalKillSwitch, intent_digest


def verify(public_key: str, digest: str, signature: str) -> bool:
    return signature == f"{public_key}:{digest}"


def test_scoped_external_approval_replay_and_expiry(tmp_path):
    path = str(tmp_path / "controls.sqlite3")
    controls = ApprovalKillSwitch(path, verify)
    digest = intent_digest("intent-1", "SPY:BUY:2")
    assert controls.approve("approval-1", "intent-1", "SPY:BUY:2", "requester", "owner",
                            "public-key", f"public-key:{digest}", datetime.now(timezone.utc) + timedelta(minutes=5)) == digest
    with pytest.raises(ApprovalError, match="replay"):
        controls.approve("approval-2", "intent-1", "SPY:BUY:2", "requester", "owner",
                         "public-key", f"public-key:{digest}", datetime.now(timezone.utc) + timedelta(minutes=5))
    with pytest.raises(ApprovalError, match="distinct"):
        controls.approve("approval-3", "intent-2", "SPY:BUY:2", "same", "same", "public-key",
                         "bad", datetime.now(timezone.utc) + timedelta(minutes=5))
    controls.close()


def test_kill_switch_persists_and_requires_separate_clearance(tmp_path):
    path = str(tmp_path / "controls.sqlite3")
    controls = ApprovalKillSwitch(path, verify)
    controls.trip("operator-a", "uncertain outcome")
    controls.close()
    recovered = ApprovalKillSwitch(path, verify)
    assert recovered.is_halted()
    with pytest.raises(ApprovalError, match="separate"):
        recovered.clear("operator-a", "confirm")
    recovered.clear("operator-b", "reviewed")
    assert not recovered.is_halted()
    recovered.close()
