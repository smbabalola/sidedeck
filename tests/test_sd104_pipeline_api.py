"""SD-104 read-only pipeline projection: provenance never upgraded, unknown inputs refused."""
from __future__ import annotations

import json

from sidedeck.application import sd103_trading_pipeline as p
from sidedeck.application.sd104_pipeline_api import pipeline_summary


def _minimal(basis=p.REAL_DATA, **extra):
    return {"schema": p.SCHEMA, "mode": "run", "data_basis": basis,
            "generated_at": "2026-10-26T09:00:00+00:00", "strategies": [], "agents": [],
            "decisions": [], "risk": [], "orders": [], "gates": {}, "broker_routes": {},
            "market_data": [], "admitted_strategies": [], "no_trade": "NO TRADE: x", **extra}


def test_missing_or_foreign_reports_are_unavailable(tmp_path):
    assert pipeline_summary(None)["status"] == "UNAVAILABLE"
    assert pipeline_summary(str(tmp_path / "none.json"))["status"] == "UNAVAILABLE"
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema": "other"}), encoding="utf-8")
    assert pipeline_summary(str(bad))["status"] == "UNAVAILABLE"
    odd = tmp_path / "odd.json"
    odd.write_text(json.dumps(_minimal(basis="DEMO_BROKER")), encoding="utf-8")
    assert pipeline_summary(str(odd))["provenance"] == "UNAVAILABLE"


def test_real_data_report_keeps_its_basis_and_replay_is_simulation(tmp_path):
    report = _minimal(replay={"performance": {"closed_trades": 2, "total_return": "0.01",
                                              "cash_reconciliation": {"status": "MATCHED"},
                                              "kill_switch": "CLEAR", "by_strategy": {}},
                              "positions": {}})
    path = tmp_path / "latest-run.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    out = pipeline_summary(str(path))
    assert out["provenance"] == p.REAL_DATA and out["execution_enabled"] is False
    assert out["replay"]["provenance"] == "SIMULATION"
    assert out["replay"]["fill_basis"] == "SIMULATED_LOCAL"


def test_values_are_bounded_and_non_numeric_numbers_dropped(tmp_path):
    report = _minimal(decisions=[{"symbol": "US:SPY", "direction": "ABSTAIN",
                                  "decision": "ABSTAIN", "strategy": [], "reasons": ["x" * 999],
                                  "stop_loss": "UNDEFINED", "entry": {"reference_close": "1"}}])
    path = tmp_path / "r.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    row = pipeline_summary(str(path))["decisions"][0]
    assert row["stop_loss"] is None and len(row["reasons"][0]) <= 240


def test_malformed_rows_and_non_finite_numbers_fail_closed(tmp_path):
    path = tmp_path / "r.json"
    path.write_text(json.dumps(_minimal(market_data=[{"sessions": "x"}])), encoding="utf-8")
    assert pipeline_summary(str(path))["status"] == "UNAVAILABLE"
    path.write_text(json.dumps(_minimal(decisions=[{
        "symbol": "US:SPY", "direction": "ABSTAIN", "decision": "ABSTAIN", "strategy": [],
        "reasons": [], "stop_loss": "+inf", "target": "Infinity",
        "entry": {"reference_close": "nan"}}])), encoding="utf-8")
    row = pipeline_summary(str(path))["decisions"][0]
    assert row["stop_loss"] is None and row["target"] is None and row["reference_close"] is None
