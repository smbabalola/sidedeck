"""Ensure the actual P5 CLI is importable and safe without upstream credentials."""
from pathlib import Path

import pytest

from sidedeck.application import p5_agents


def test_p5_launcher_compiles_and_imports():
    filename = Path(p5_agents.__file__)
    compile(filename.read_text(encoding="utf-8"), str(filename), "exec")


def test_p5_launcher_help_does_not_call_agents(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["p5_agents", "--help"])
    with pytest.raises(SystemExit) as result:
        p5_agents.main()
    assert result.value.code == 0
    assert "--models-config" in capsys.readouterr().out


def test_missing_hedge_fund_bridge_fails_closed(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr("sys.argv", [
        "p5_agents", "--models-config", "config/p5_models.example.json",
        "--tradingagents-python", "python", "--hedge-fund-python", "python",
        "--hedge-fund-bridge", str(tmp_path / "nonexistent-bridge.py"),
    ])
    assert p5_agents.main() == 2
    assert "NO-GO" in capsys.readouterr().out
