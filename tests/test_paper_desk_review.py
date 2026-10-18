"""Offline paper desk preview never reaches Alpaca or exposes credentials."""

import json
from pathlib import Path

import pytest

from sidedeck import paper_desk_review


def test_two_independent_order_previews_and_risk_gate():
    report = paper_desk_review.preview()
    assert report["mode"] == "FIXTURE_ONLY"
    assert report["paper_write_enabled"] is False
    assert report["alpaca_api_calls"] == 0
    a, b = report["orders"]
    assert a["paper_key_slot"] == "ALPACA_API_KEY"
    assert b["paper_key_slot"] == "ALPACA_API_KEY2"
    assert a["client_order_id"] != b["client_order_id"]
    assert all(order["capital_usd"] == "1000" for order in report["orders"])
    assert all(order["risk"] == "ACCEPTED" for order in report["orders"])
    assert all(order["paper_orders_sent"] == "0" for order in report["orders"])


def test_static_page_is_not_an_order_interface():
    page = paper_desk_review.html_review(paper_desk_review.preview())
    assert "OFFLINE FIXTURE" in page
    assert "No Alpaca API requests or paper trades" in page
    assert "ALPACA_API_KEY2" in page
    assert "<button" not in page and "<form" not in page


def test_cli_requires_explicit_dry_run(monkeypatch):
    monkeypatch.setattr("sys.argv", ["paper_desk_review"])
    with pytest.raises(SystemExit):
        paper_desk_review.main()


def test_cli_writes_ignored_separate_preview_files(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["paper_desk_review", "--dry-run"])
    assert paper_desk_review.main() == 0
    meta = json.loads(capsys.readouterr().out)
    assert meta["alpaca_api_calls"] == meta["orders_sent"] == 0
    assert Path(meta["html"]).exists()
    report = json.loads(Path(meta["json"]).read_text(encoding="utf-8"))
    assert len(report["orders"]) == 2
