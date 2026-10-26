"""SD-104 read-only projection of the latest SD-103 pipeline run for ``/api/pipeline/latest``.

Only a report whose ``schema`` is the SD-103 schema is accepted. Fields are allowlisted and
length-bounded before they reach the browser. Provenance is derived from the report and never
upgraded: research panels carry the run's data basis (``REAL_DATA`` or ``SYNTHETIC_FIXTURE``);
everything from the replay ledger is ``SIMULATION`` (fills are SIMULATED_LOCAL). There are no
controls and no write path; ``execution_enabled`` is always false.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sidedeck.application.sd103_trading_pipeline import FIXTURE, REAL_DATA, SCHEMA

MAX_TEXT = 240
MAX_ROWS = 200


def _t(value: Any) -> str | None:
    return None if value is None else str(value)[:MAX_TEXT]


def _num(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    try:
        if text.upper() in ("UNDEFINED", "NAN", "INF", "-INF"):
            return None
        float(text)
    except ValueError:
        return None
    return text[:40]


def _strs(values: Any, limit: int = 20) -> list[str]:
    return [str(v)[:MAX_TEXT] for v in (values or [])][:limit]


def unavailable(reason: str) -> dict[str, Any]:
    return {"schema_version": 1, "status": "UNAVAILABLE", "reason": reason[:MAX_TEXT],
            "execution_enabled": False, "provenance": "UNAVAILABLE"}


def pipeline_summary(report_path: str | None) -> dict[str, Any]:
    if not report_path:
        return unavailable("No pipeline report configured")
    target = Path(report_path)
    if not target.is_file() or target.is_symlink():
        return unavailable("No pipeline run yet: run python -m "
                           "sidedeck.application.sd103_trading_pipeline run")
    try:
        report = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return unavailable("Pipeline report is unreadable")
    if not isinstance(report, dict) or report.get("schema") != SCHEMA:
        return unavailable("Pipeline report has an unknown schema")
    basis = report.get("data_basis")
    if basis not in (REAL_DATA, FIXTURE):
        return unavailable("Pipeline report has an unknown data basis")
    scanner = report.get("scanner") or {}
    out: dict[str, Any] = {
        "schema_version": 1, "status": "AVAILABLE", "execution_enabled": False,
        "provenance": basis, "mode": _t(report.get("mode")),
        "generated_at": _t(report.get("generated_at")),
        "cutoff_session": _t(report.get("cutoff_session")),
        "admission_through": _t(report.get("admission_through")),
        "data_freshness": {k: _t(v) for k, v in (report.get("data_freshness") or {}).items()},
        "market_data": [{"canonical_id": _t(m.get("canonical_id")), "first": _t(m.get("first")),
                         "last": _t(m.get("last")), "sessions": int(m.get("sessions", 0)),
                         "limitations": _strs(m.get("limitations"))}
                        for m in report.get("market_data", [])][:MAX_ROWS],
        "excluded_instruments": {str(k)[:40]: _t(v) for k, v in
                                 (report.get("excluded_instruments") or {}).items()},
        "scanner": {"status": _t(scanner.get("status", "NOT_RUN")),
                    "scanned": int(scanner.get("scanned", 0) or 0),
                    "shortlist": [{"canonical_id": _t(c.get("canonical_id")),
                                   "rank": int(c.get("rank", 0)), "score": _num(c.get("score"))}
                                  for c in scanner.get("shortlist", [])][:MAX_ROWS],
                    "filtered": [[_t(f[0]), _t(f[1])] for f in scanner.get("filtered", [])
                                 if isinstance(f, list) and len(f) == 2][:MAX_ROWS],
                    "note": _t(scanner.get("note"))},
        "strategies": [{
            "instrument": _t(s.get("instrument")), "strategy_id": _t(s.get("strategy_id")),
            "version": _t(s.get("version")), "admission": _t(s.get("admission")),
            "admission_without_override": _t(s.get("admission_without_override")),
            "override": _t(s.get("override")),
            "reasons": _strs(s.get("admission_reasons")),
            "entry": _t(s.get("entry")), "exit": _t(s.get("exit")),
            "stop_loss": _t(s.get("stop_loss")), "target": _t(s.get("target")),
            "holding_period_sessions": [int(x) for x in s.get("holding_period_sessions", [])][:2],
            "completed_trades": int((s.get("historical") or {}).get("completed_trade_count", 0)),
            "profit_factor": _num((s.get("historical") or {}).get("profit_factor")),
            "max_drawdown": _num((s.get("historical") or {}).get("max_drawdown")),
            "oos_trades": int((s.get("out_of_sample") or {}).get("oos_trades", 0)),
            "oos_profit_factor": _num((s.get("out_of_sample") or {}).get("oos_profit_factor")),
            "oos_ending_equity": _num((s.get("out_of_sample") or {}).get("oos_ending_equity")),
        } for s in report.get("strategies", [])][:MAX_ROWS],
        "agents": [{"portfolio": _t(a.get("portfolio")), "instrument": _t(a.get("instrument")),
                    "status": _t(a.get("status")), "reason": _t(a.get("reason")),
                    "direction": _t(a.get("direction")), "model": _t(a.get("model"))}
                   for a in report.get("agents", [])][:MAX_ROWS],
        "decisions": [{
            "symbol": _t(d.get("symbol")), "direction": _t(d.get("direction")),
            "decision": _t(d.get("decision")), "strategy": _strs(d.get("strategy")),
            "reference_close": _num((d.get("entry") or {}).get("reference_close")),
            "stop_loss": _num(d.get("stop_loss")), "target": _num(d.get("target")),
            "quantity": _num(d.get("quantity")),
            "capital_required_usd": _num(d.get("capital_required_usd")),
            "risk_reward": _num(d.get("risk_reward")),
            "holding_period": _t(d.get("holding_period")), "reasons": _strs(d.get("reasons")),
        } for d in report.get("decisions", [])][:MAX_ROWS],
        "risk": [{"canonical_id": _t(r.get("canonical_id")), "decision": _t(r.get("decision")),
                  "reasons": _strs(r.get("reasons")),
                  "capital_required_usd": _num(r.get("capital_required_usd"))}
                 for r in report.get("risk", [])][:MAX_ROWS],
        "orders": [{"intent_id": _t(o.get("intent_id")), "canonical_id": _t(o.get("canonical_id")),
                    "units": _num(o.get("units")), "limit_price": _num(o.get("limit_price")),
                    "stop_price": _num(o.get("stop_price")), "strategy": _t(o.get("strategy")),
                    "broker_route": _t(o.get("broker_route")), "status": _t(o.get("status"))}
                   for o in report.get("orders", [])][:MAX_ROWS],
        "no_trade": _t(report.get("no_trade")),
        "admitted_strategies": _strs(report.get("admitted_strategies"), MAX_ROWS),
        "broker_routes": {str(k)[:40]: _t(v) for k, v in
                          (report.get("broker_routes") or {}).items()},
        "gates": {str(k)[:40]: _t(v) for k, v in (report.get("gates") or {}).items()},
        "replay": None}
    replay = report.get("replay")
    if isinstance(replay, dict):
        perf = replay.get("performance") or {}
        out["replay"] = {
            "provenance": "SIMULATION", "fill_basis": "SIMULATED_LOCAL",
            "basis": _t(perf.get("basis")), "window": _strs(perf.get("window"), 2),
            "closed_trades": int(perf.get("closed_trades", 0)),
            "open_positions": int(perf.get("open_positions", 0)),
            "total_return": _num(perf.get("total_return")),
            "max_drawdown": _num(perf.get("max_drawdown")),
            "realized_pnl_usd": _num(perf.get("realized_pnl_usd")),
            "fees_usd": _num(perf.get("fees_usd")),
            "benchmark": _num(perf.get("benchmark_equal_weight_price_return")),
            "cash_reconciliation": _t((perf.get("cash_reconciliation") or {}).get("status")),
            "kill_switch": _t(perf.get("kill_switch")), "halt_reason": _t(perf.get("halt_reason")),
            "by_strategy": [{"strategy": str(k)[:80], "closed_trades": int(v.get("closed_trades", 0)),
                             "win_rate": _num(v.get("win_rate")),
                             "profit_factor": _num(v.get("profit_factor")),
                             "net_pnl_usd": _num(v.get("net_pnl_usd")),
                             "verdict": _t(v.get("verdict"))}
                            for k, v in (perf.get("by_strategy") or {}).items()][:MAX_ROWS],
            "positions": [{"ref": str(k)[:40], "canonical_id": _t(v.get("canonical_id")),
                           "strategy": _t(v.get("strategy")), "opened": _t(v.get("opened")),
                           "closed": _t(v.get("closed")), "fill_status": _t(v.get("fill_status")),
                           "units": _num(v.get("units_filled")),
                           "entry_price": _num(v.get("entry_price")),
                           "exit_price": _num(v.get("exit_price")),
                           "exit_reason": _t(v.get("exit_reason")),
                           "realized_pnl": _num(v.get("realized_pnl"))}
                          for k, v in (replay.get("positions") or {}).items()][-MAX_ROWS:]}
    return out
