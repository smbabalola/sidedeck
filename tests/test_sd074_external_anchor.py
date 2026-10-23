"""SD-074D off-machine checkpoint check: rollback, deletion, replacement and checkpoint replay
are detected; unpublished state cannot pass the publish-before-send gate."""
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
    keeper.initialize(env.ledger, LEDGER_ID, NOW)                    # genesis at creation
    yield env, remote, keeper, tmp_path
    env.ledger.close()


def _files(env: _Env) -> tuple[Path, Path]:
    return env.tmp / "sd063.sqlite3", env.tmp / "sd063.anchor.json"


def _backup(env: _Env, folder: Path) -> None:
    folder.mkdir()
    env.ledger.close()
    for path in _files(env):
        shutil.copy(path, folder / path.name)
    env.ledger = env.open_ledger()
    env.rt = env.runtime(env.ledger, env.authority)


def _restore(env: _Env, folder: Path) -> None:
    env.ledger.close()
    for path in _files(env):
        shutil.copy(folder / path.name, path)
    env.ledger = env.open_ledger()
    env.rt = env.runtime(env.ledger, env.authority)


def test_publish_verify_and_publish_before_send_gate(setup):
    env, _, keeper, _ = setup
    env.entry()
    with pytest.raises(PolicyRefused, match="publish before sending"):
        keeper.require_published(env.ledger, LEDGER_ID)
    first = keeper.publish(env.ledger, LEDGER_ID, NOW)
    keeper.require_published(env.ledger, LEDGER_ID)
    assert keeper.publish(env.ledger, LEDGER_ID, NOW) == first      # nothing new: no append
    env.ledger.trip_kill_switch("operator", NOW)
    assert keeper.publish(env.ledger, LEDGER_ID, NOW).count == first.count + 1


def test_rollback_to_an_older_consistent_pair_is_detected(setup):
    env, _, keeper, tmp = setup
    env.entry()
    keeper.publish(env.ledger, LEDGER_ID, NOW)
    _backup(env, tmp / "backup")
    env.ledger.trip_kill_switch("operator", NOW)
    keeper.publish(env.ledger, LEDGER_ID, NOW)
    _restore(env, tmp / "backup")
    assert not env.ledger.kill_switch_engaged()                       # locally consistent
    with pytest.raises(PolicyRefused, match="behind its published checkpoint"):
        keeper.verify(env.ledger, LEDGER_ID)


def test_e1_replaying_an_old_checkpoint_as_the_latest_is_refused(setup):
    env, _, keeper, tmp = setup
    env.entry()
    keeper.publish(env.ledger, LEDGER_ID, NOW)
    _backup(env, tmp / "backup")
    env.ledger.trip_kill_switch("operator", NOW)
    keeper.publish(env.ledger, LEDGER_ID, NOW)
    _restore(env, tmp / "backup")
    remote = tmp / "remote"
    old = sorted(remote.glob("*.json"))[1]                            # the count-N checkpoint
    shutil.copy(old, remote / f"{LEDGER_ID}.999999999999.json")       # name claims a later one
    with pytest.raises(PolicyRefused, match="failing closed"):
        keeper.verify(env.ledger, LEDGER_ID)
    (remote / f"{LEDGER_ID}.999999999999.json").unlink()
    data = json.loads(old.read_text(encoding="utf-8"))               # same content, right name
    data_path = remote / f"{LEDGER_ID}.{data['count'] + 100:012d}.json"
    data_path.write_text(json.dumps({**data, "count": data["count"] + 100}), encoding="utf-8")
    with pytest.raises(PolicyRefused, match="not authentic"):
        keeper.verify(env.ledger, LEDGER_ID)


def test_e2_unpublished_tail_cannot_be_sent(setup):
    env, _, keeper, tmp = setup
    keeper.publish(env.ledger, LEDGER_ID, NOW)
    _backup(env, tmp / "backup")
    env.entry()                                                       # proposal, unpublished
    with pytest.raises(PolicyRefused, match="publish before sending"):
        keeper.require_published(env.ledger, LEDGER_ID)
    _restore(env, tmp / "backup")                                     # tail rolled back
    keeper.verify(env.ledger, LEDGER_ID)                              # undetectable by design,
    keeper.require_published(env.ledger, LEDGER_ID)                   # but nothing was sent


def test_e3_ledger_with_events_but_no_history_is_refused(tmp_path):
    (tmp_path / "host").mkdir()
    env = _Env(tmp_path / "host")
    keeper = AnchorKeeper(WriteOnceDirectoryAnchor(tmp_path / "remote"), DEVICE_KEY)
    try:
        keeper.verify(env.ledger, LEDGER_ID)                          # empty and unpublished: ok
        env.ledger.trip_kill_switch("x", NOW)
        with pytest.raises(PolicyRefused, match="no published checkpoint"):
            keeper.verify(env.ledger, LEDGER_ID)
        with pytest.raises(PolicyRefused, match="no published checkpoint"):
            keeper.publish(env.ledger, LEDGER_ID, NOW)
        with pytest.raises(PolicyRefused, match="empty ledger"):
            keeper.initialize(env.ledger, LEDGER_ID, NOW)
    finally:
        env.ledger.close()


def test_deleting_both_files_cannot_start_fresh(setup):
    env, _, keeper, _ = setup
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
    env, _, keeper, _ = setup
    env.ledger.trip_kill_switch("first", NOW)
    keeper.publish(env.ledger, LEDGER_ID, NOW)
    env.ledger.close()
    for path in _files(env):
        path.unlink()
    env.ledger = env.open_ledger()                                     # forged, same length
    env.ledger.trip_kill_switch("different content", NOW + timedelta(seconds=1))
    with pytest.raises(PolicyRefused, match="diverges"):
        keeper.verify(env.ledger, LEDGER_ID)


def test_tampered_or_foreign_checkpoints_are_refused(setup):
    env, remote, keeper, tmp = setup
    env.entry()
    keeper.publish(env.ledger, LEDGER_ID, NOW)
    path = sorted((tmp / "remote").glob("*.json"))[-1]
    data = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps({**data, "head": "f" * 64}), encoding="utf-8")
    with pytest.raises(PolicyRefused, match="not authentic"):
        keeper.verify(env.ledger, LEDGER_ID)
    path.write_text(json.dumps(data), encoding="utf-8")
    other_device = AnchorKeeper(remote, b"another-device-key-of-32-bytes-or-more!!")
    with pytest.raises(PolicyRefused, match="not authentic"):
        other_device.verify(env.ledger, LEDGER_ID)


def test_unavailable_external_anchor_fails_closed(setup):
    env, _, _, _ = setup

    class Down:
        def history(self, ledger_id: str) -> list[Checkpoint]:
            raise OSError("network unreachable")

        def append(self, checkpoint: Checkpoint) -> None:
            raise OSError("network unreachable")

    keeper = AnchorKeeper(Down(), DEVICE_KEY)
    with pytest.raises(PolicyRefused, match="failing closed"):
        keeper.verify(env.ledger, LEDGER_ID)
    with pytest.raises(PolicyRefused, match="failing closed"):
        keeper.publish(env.ledger, LEDGER_ID, NOW)


def test_the_stand_in_store_is_write_once_and_inputs_are_checked(setup):
    env, remote, keeper, _ = setup
    env.ledger.trip_kill_switch("x", NOW)
    cp = keeper.publish(env.ledger, LEDGER_ID, NOW)
    with pytest.raises(PolicyRefused, match="write-once"):
        remote.append(replace(cp, head="f" * 64))
    with pytest.raises(PolicyRefused, match="invalid checkpoint identity"):
        remote.append(replace(cp, ledger_id="../escape"))
    with pytest.raises(PolicyRefused, match="32 bytes"):
        AnchorKeeper(remote, b"short")
    with pytest.raises(PolicyRefused, match="invalid ledger id"):
        keeper.verify(env.ledger, "../escape")
