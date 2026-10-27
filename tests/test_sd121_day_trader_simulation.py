from pathlib import Path

import pytest

from sidedeck.application.sd121_day_trader_simulation import run_simulation


def test_explicit_fixture_lifecycle_restarts_and_reconciles(tmp_path: Path) -> None:
    with pytest.raises(PermissionError, match="explicit fixture_acceptance"):
        run_simulation(tmp_path / "no-consent")
    report = run_simulation(tmp_path / "accepted", fixture_acceptance=True)
    assert [event["stage"] for event in report["events"]] == [
        "SCAN", "SIGNAL", "DECISION", "SIMULATED_ORDER", "FILL",
        "POSITION_MANAGEMENT", "CLOSE", "RECONCILIATION",
    ]
    assert report["decision"] == "ELIGIBLE"
    assert report["broker_execution"] == "DISABLED"
    assert report["production_admission"] == "UNCHANGED"
    assert report["reconciliation"] == "MATCHED"
    assert report["open_positions_after_restart"] == 0
    assert report["event_count"] == 8
    assert len(report["event_sha256"]) == 64


def test_simulation_refuses_reusing_a_ledger_directory(tmp_path: Path) -> None:
    workdir = tmp_path / "single-use"
    run_simulation(workdir, fixture_acceptance=True)
    with pytest.raises(ValueError, match="fresh directory"):
        run_simulation(workdir, fixture_acceptance=True)
