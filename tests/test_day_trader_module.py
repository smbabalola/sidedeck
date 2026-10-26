from pathlib import Path

import pytest

from sidedeck.modules.day_trader.manifest import SKILLS, resolve, verify
from sidedeck.modules.day_trader.sandbox import SandboxRefused, Workspace, environment_preview, run_raw


def test_pinned_skill_resolves_to_verified_source() -> None:
    result = resolve()
    assert result.status == "VERIFIED"
    assert result.source in ("INSTALLED_PLUGIN", "VENDORED")
    assert len(result.checked) == 12
    assert len(SKILLS) == 11


def test_manifest_refuses_missing_or_modified_source(tmp_path: Path) -> None:
    root = tmp_path / "skill"
    root.mkdir()
    assert verify(root, "TEST").status == "MISMATCH"
    (root / "LICENSE").write_text("not the license", encoding="utf-8")
    assert verify(root, "TEST").status == "MISMATCH"


def test_sandbox_probe_is_blocked_and_env_is_minimal() -> None:
    ws = Workspace()
    try:
        result = run_raw("import socket; socket.create_connection(('example.com', 80))", ws)
        assert result.returncode != 0
        assert b"SIDEDECK_SANDBOX_BLOCKED" in result.stderr
        names = environment_preview({"ALPACA_API_KEY": "secret", "OPENAI_API_KEY": "secret"})
        assert "ALPACA_API_KEY" not in names
        assert "OPENAI_API_KEY" not in names
    finally:
        ws.close()


def test_sandbox_probe_cannot_spawn_a_child_process() -> None:
    ws = Workspace()
    try:
        result = run_raw("import subprocess; subprocess.run(['cmd', '/c', 'echo escaped'])", ws)
        assert result.returncode != 0
        assert b"SIDEDECK_SANDBOX_BLOCKED" in result.stderr
    finally:
        ws.close()


def test_sandbox_refuses_network_skill_without_offline_and_absolute_paths() -> None:
    ws = Workspace()
    try:
        from sidedeck.modules.day_trader.sandbox import _check_args

        with pytest.raises(SandboxRefused):
            _check_args("trader-scanner", "orb", [], ws)
        with pytest.raises(SandboxRefused):
            _check_args("trader-scanner", "orb", ["--offline", "C:\\secrets.json"], ws)
        with pytest.raises(SandboxRefused):
            _check_args("trader-broker", "approve", ["--offline"], ws)
    finally:
        ws.close()
