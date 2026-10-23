"""SD-074D off-machine checkpoint check: rollback, deletion and replacement are detected."""
from __future__ import annotations

import json
import shutil
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from sidedeck.application.sd063_autonomous_demo_policy import PolicyRefused
from sidedeck.application.sd074_external_anchor import (
    AnchorKeeper, Checkpoint, WriteOnceDirectoryAnchor,
)
from test_sd063_autonomous_demo_policy import NOW, _Env

DEVICE_KEY = b"device-key-held-in-the-os-keystore-0001"
LEDGER_ID = "policy-7b0c3e52"


@pytest.fixture
def setup(tmp_path: Path):
    (tmp_path / "host").mkdir()
    env = _Env(tmp_path / "host")
    remote = WriteOnceDirectoryAnchor(tmp_path / "remote")
    keeper = AnchorKeeper(remote, DEVICE_KEY)
    yield env, remote, keeper
    env.ledger.close()


def _files(env: _Env) -> tuple[Path, Path]:
    return env.tmp / "sd063.sqlite3", env.tmp / "sd063.anchor.json"


def test_publish_and_verify_a_consistent_ledger(setup):
    env, _, keeper = setup
    env.entry()
    first = keeper.publish(env.ledger, LEDGER_ID, NOW)
    keeper.verify(env.ledger, LEDGER_ID)
    assert keeper.publish(env.ledger, LEDGER_ID, NOW) == first      # nothing new: no append
    env.ledger.trip_kill_switch("operator", NOW)
    assert keeper.publish(env.ledger, LEDGER_ID, NOW).count == first.count + 1


def test_rollback_to_an_older_consistent_pair_is_detected(setup, tmp_path):
    env, _, keeper = setup
    env.entry()
    keeper.publish(env.ledger, LEDGER_ID, NOW)
    db, anchor = _files(env)
    backup = tmp_path / "backup"
    backup.mkdir()
    env.ledger.close()
    shutil.copy(db, backup / db.name)
    shutil.copy(anchor, backup / anchor.name)
    env.ledger = env.open_ledger()
    env.ledger.trip_kill_switch("operator", NOW)                       # later state published
    keeper.publish(env.ledger, LEDGER_ID, NOW)
    env.ledger.close()
    shutil.copy(backup / db.name, db)                                  # roll both files back
    shutil.copy(backup / anchor.name, anchor)
    env.ledger = env.open_ledger()                                     # locally consistent
    assert not env.ledger.kill_switch_engaged()
    with pytest.raises(PolicyRefused, match="behind its published checkpoint"):
        keeper.verify(env.ledger, LEDGER_ID)


def test_deleting_both_files_cannot_start_fresh(setup):
    env, _, keeper = setup
    env.entry()
    keeper.publish(env.ledger, LEDGER_ID, NOW)
    env.ledger.close()
    for path in _files(env):
        path.unlink()
    with pytest.raises(PolicyRefused, match="refusing a fresh start"):
        keeper.require_no_history(LEDGER_ID)
    env.ledger = env.open_ledger()                                     # fresh pair on disk
    with pytest.raises(PolicyRefused, match="behind its published checkpoint"):
        keeper.verify(env.ledger, LEDGER_ID)


def test_replacement_with_a_forged_pair_is_detected(setup):
    env, _, keeper = setup
    env.ledger.trip_kill_switch("first", NOW)
    keeper.publish(env.ledger, LEDGER_ID, NOW)
    env.ledger.close()
    for path in _files(env):
        path.unlink()
    env.ledger = env.open_ledger()                                     # forged, same length
    env.ledger.trip_kill_switch("different content", NOW + timedelta(seconds=1))
    with pytest.raises(PolicyRefused, match="diverges"):
        keeper.verify(env.ledger, LEDGER_ID)


def test_tampered_or_foreign_checkpoints_are_refused(setup, tmp_path):
    env, remote, keeper = setup
    env.entry()
    keeper.publish(env.ledger, LEDGER_ID, NOW)
    path = sorted((tmp_path / "remote").glob("*.json"))[-1]
    data = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps({**data, "count": 0}), encoding="utf-8")
    with pytest.raises(PolicyRefused, match="not authentic"):
        keeper.verify(env.ledger, LEDGER_ID)
    path.write_text(json.dumps(data), encoding="utf-8")
    other_device = AnchorKeeper(remote, b"another-device-key-of-32-bytes-or-more!!")
    with pytest.raises(PolicyRefused, match="not authentic"):
        other_device.verify(env.ledger, LEDGER_ID)


def test_unavailable_external_anchor_fails_closed(setup):
    env, _, _ = setup

    class Down:
        def latest(self, ledger_id: str) -> Checkpoint | None:
            raise OSError("network unreachable")

        def append(self, checkpoint: Checkpoint) -> None:
            raise OSError("network unreachable")

    keeper = AnchorKeeper(Down(), DEVICE_KEY)
    with pytest.raises(PolicyRefused, match="failing closed"):
        keeper.verify(env.ledger, LEDGER_ID)
    with pytest.raises(PolicyRefused, match="failing closed"):
        keeper.publish(env.ledger, LEDGER_ID, NOW)


def test_the_stand_in_store_is_write_once_and_inputs_are_checked(setup):
    env, remote, keeper = setup
    env.ledger.trip_kill_switch("x", NOW)
    cp = keeper.publish(env.ledger, LEDGER_ID, NOW)
    with pytest.raises(PolicyRefused, match="write-once"):
        remote.append(replace(cp, head="f" * 64))
    with pytest.raises(PolicyRefused, match="32 bytes"):
        AnchorKeeper(remote, b"short")
    with pytest.raises(PolicyRefused, match="invalid ledger id"):
        keeper.verify(env.ledger, "../escape")
