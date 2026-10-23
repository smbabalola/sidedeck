"""Persistent paper desk fixture CLI can restart without duplicated fills."""

from pathlib import Path
import json
import sqlite3

import pytest

from sidedeck import paper_outbox_demo


def test_repeat_offline_run_restores_existing_fill_without_double_posting(tmp_path):
    path = tmp_path / "paper_outbox_fixture.sqlite3"
    first = paper_outbox_demo.run_offline(path)
    second = paper_outbox_demo.run_offline(path)
    assert first == second
    assert first["mode"] == "LOCAL_FIXTURE_NO_ALPACA"
    assert first["paper_orders_submitted"] == first["provider_requests"] == 0
    portfolios = first["result"]["strategies"]
    assert portfolios["tradingagents"]["cash"] == "900"
    assert portfolios["ai-trading"]["cash"] == "1000"
    assert portfolios["tradingagents"]["positions"] == {"US:AAPL": "1"}
    assert portfolios["ai-trading"]["positions"] == {}
    assert portfolios["tradingagents"]["orders"][0]["state"] == "FILLED"
    assert portfolios["ai-trading"]["orders"][0]["state"] == "PREPARED"
    assert paper_outbox_demo.run_offline(path)["result"]["kill_switch_engaged"] is True
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM paper_events").fetchone()[0] == 3
        assert db.execute("SELECT count(*) FROM paper_fills").fetchone()[0] == 1


def test_cli_requires_dry_run_and_only_writes_dedicated_ignored_files(
    tmp_path, monkeypatch, capsys,
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["paper_outbox_demo"])
    with pytest.raises(SystemExit):
        paper_outbox_demo.main()
    monkeypatch.setattr("sys.argv", ["paper_outbox_demo", "--dry-run"])
    assert paper_outbox_demo.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["provider_requests"] == 0
    assert payload["paper_orders_submitted"] == 0
    assert Path(payload["persistent_file"]).exists()
    page = Path(payload["html"]).read_text(encoding="utf-8")
    assert "OFFLINE FIXTURE" in page
    assert "No provider account accessed" in page
    assert Path(payload["json"]).exists()


def test_dry_run_does_not_read_environment_or_secrets(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ALPACA_API_KEY", "DONT_READ_KEY")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "DONT_READ_SECRET")
    report = paper_outbox_demo.run_offline()
    assert "DONT_READ_KEY" not in str(report)
    assert "DONT_READ_SECRET" not in str(report)
