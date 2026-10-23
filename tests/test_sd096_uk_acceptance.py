from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Any

import pytest

from sidedeck.application.sd096_uk_acceptance import (
    genuine_data_inventory,
    main,
    run_acceptance,
)
from uk_import_helpers import NOW, build_uk_dir


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_: Any, **__: Any) -> None:
        raise AssertionError("network access attempted in an offline UK test")
    monkeypatch.setattr(socket.socket, "connect", refuse)


def test_acceptance_report_separates_genuine_fixture_and_simulation(tmp_path: Path) -> None:
    report = run_acceptance(tmp_path / "no-data", tmp_path / "work")
    genuine = report["genuine_data"]
    assert genuine["status"] == "NO_GENUINE_UK_DATA" and genuine["blocker"]
    assert [c["result"] for c in genuine["candidates"]] == ["ABSTAIN"] * 5
    assert all("NO_APPROVED_MARKET_DATA" in c["reasons"] for c in genuine["candidates"])
    scan = report["fixture_scan"]
    assert scan["data_basis"] == "SYNTHETIC_FIXTURE"
    assert scan["acceptance"] == "ABSTAIN_NO_GENUINE_DATA_FIXTURE_RUN"
    assert all(i["isin"].startswith("ZZ") for i in scan["identities"])  # unmistakably synthetic
    trade = report["simulated_trade"]
    assert trade["label"] == "SIMULATION"
    assert trade["intent_source"] == "CONTROLLED_EXECUTION_FIXTURE"
    assert trade["entry"]["status"] == trade["exit"]["status"] == "FILLED"
    assert trade["final_reconciliation"]["status"] == "MATCHED"
    assert trade["final_reconciliation"]["open_positions"] == 0
    src, gbp = trade["gbx_to_gbp"]["source_ask"], trade["gbx_to_gbp"]["normalized_ask_gbp"]
    assert float(src) == pytest.approx(float(gbp) * 100)
    scenarios = report["scenarios"]
    assert scenarios["stale_market_data"] == "STALE_QUOTE"
    assert scenarios["missing_broker_mapping"] == "MISSING_VENUE_MAPPING"
    assert scenarios["market_closed"] == scenarios["after_close_same_day"] == "MARKET_CLOSED"
    assert scenarios["minimum_order_violation"] in ("BELOW_MINIMUM_ORDER",
                                                    "NOT_APPLICABLE_PRICE_ABOVE_MINIMUM")
    assert scenarios["partial_fill"].startswith("PARTIALLY_FILLED")
    assert scenarios["duplicate_order"].endswith("fills=1")
    assert "submissions=1" in scenarios["interrupted_execution"]
    assert scenarios["unknown_exit_outcome"].startswith("UNRESOLVED;kill_switch=True")
    assert scenarios["protected_portfolio_separation"].startswith(
        "PROTECTED_OR_NON_SIMULATION_BOOK")
    assert scenarios["gbx_ambiguous_unit_label"].startswith("REFUSED:UNKNOWN_OR_AMBIGUOUS_UNIT")
    assert report["execution_permission"] == "NOT_GRANTED"


def test_owner_files_without_a_licence_statement_are_refused(tmp_path: Path) -> None:
    root = build_uk_dir(tmp_path / "uk", licence="")
    inv = genuine_data_inventory(root, NOW)
    assert inv["import"]["status"] == "MANIFEST_INVALID"
    assert ["manifest", "LICENCE_AND_SOURCE_REQUIRED"] in inv["import"]["rejected"]
    assert inv["status"] == "GENUINE_IMPORT_MANIFEST_INVALID" and inv["blocker"]


def test_sourced_listing_without_bars_still_abstains(tmp_path: Path) -> None:
    root = build_uk_dir(tmp_path / "uk")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    manifest["bars"] = []
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    inv = genuine_data_inventory(root, NOW)
    assert inv["import"]["status"] == "IMPORTED_NO_PRICE_DATA"
    bp = next(c for c in inv["candidates"] if c["proposed_tidm"] == "BP.")
    assert bp["result"] == "ABSTAIN" and "NO_APPROVED_MARKET_DATA" in bp["reasons"]
    assert inv["real_scan"] is None


def test_cli_writes_the_report_for_the_dashboard(tmp_path: Path,
                                                 capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "uk-acceptance.json"
    main(["--data-dir", str(tmp_path / "none"), "--out", str(out)])
    assert json.loads(out.read_text(encoding="utf-8"))["report"] == "sd096.uk_morning_acceptance.v1"
    capsys.readouterr()


def test_cli_prints_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["--data-dir", str(tmp_path)])
    out = json.loads(capsys.readouterr().out)
    assert out["report"] == "sd096.uk_morning_acceptance.v1"
    assert out["us_msft_pilot"].startswith("UNTOUCHED")
