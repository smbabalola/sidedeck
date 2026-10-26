from pathlib import Path

from sidedeck.application.sd114_day_trader_runs import RunStore, day_trader_run_summary
from sidedeck.modules.day_trader.orchestrator import DayTraderConfig, run_module, upstream_fixture_inputs


def test_fixture_workflow_persists_provenance_and_decision_boundary(tmp_path: Path) -> None:
    root = Path("third_party/day-trader-skill")
    report = run_module(upstream_fixture_inputs(root), DayTraderConfig(mode="SIMULATION_ONLY"))
    store = RunStore(tmp_path / "runs.sqlite3")
    try:
        run_id = store.save(report)
        latest = store.latest()
        assert latest is not None and latest["run_id"] == run_id
        assert latest["basis"] == "UPSTREAM_FIXTURE_UNAPPROVED_SOURCE"
        assert latest["opportunities"]
        assert latest["plans"] and latest["plans"][0]["proposal"]["sidedeck_decision"]["status"] == "WATCHLIST"
        assert latest["simulations"]["label"] == "SIMULATION_ONLY_NOT_PERFORMANCE_EVIDENCE"
        assert latest["errors"] == []
        assert len(latest["report_sha256"]) == 64
    finally:
        store.close()


def test_summary_has_bounded_empty_state(tmp_path: Path) -> None:
    missing = tmp_path / "missing.sqlite3"
    summary = day_trader_run_summary(str(missing))
    assert summary["latest"] is None
    assert summary["runs"] == []
    assert summary["data_status"] == "NO_SAVED_RUN"
    assert not missing.exists()
