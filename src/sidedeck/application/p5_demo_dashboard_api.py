"""Loopback-only, read-only dashboard API for saved eToro Demo baseline metadata.

No eToro HTTP calls, credentials, monetary values, raw IDs, or database writes.
The captured baseline is historical evidence, NOT a fresh reconciliation.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from sidedeck.application.sd014_strategy_engine import catalogue
from sidedeck.application.sd036_etoro_demo_desk import etoro_demo_status
from sidedeck.application.sd073_market_tracks_api import market_tracks_summary
from sidedeck.application.sd082_scan_snapshot import scan_snapshot_summary
from sidedeck.application.sd086_ops_api import authorization_ledger_summary, track_ledgers_summary
from sidedeck.application.sd097_uk_markets_api import uk_markets_summary
from sidedeck.application.sd104_pipeline_api import pipeline_summary
from sidedeck.application.sd109_research_schedule import history_summary
from sidedeck.application.sd113_day_trader_api import day_trader_summary


def baseline_summary(db_path: str) -> dict[str, Any]:
    path = Path(db_path).resolve(strict=True)
    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    try:
        row = db.execute(
            "SELECT captured_at, position_count FROM etoro_demo_baseline_capture "
            "WHERE capture_id=1"
        ).fetchone()
        if row is None:
            return {"baseline_status": "NOT_CAPTURED", "captured_at": None,
                    "protected_positions": None}
        captured = datetime.fromisoformat(row[0])
        if captured.tzinfo is None or type(row[1]) is not int or row[1] < 0:
            raise ValueError("invalid saved baseline")
        count = db.execute("SELECT count(*) FROM etoro_demo_baseline").fetchone()[0]
        if count != row[1]:
            raise ValueError("baseline count mismatch")
        return {"baseline_status": "CAPTURED", "captured_at": captured.isoformat(),
                "protected_positions": count}
    finally:
        db.close()


def read_refresh(path: str | None, *, now: datetime | None = None) -> dict[str, Any] | None:
    if not path:
        return None
    target = Path(path)
    if not target.is_file() or target.is_symlink():
        return None
    try:
        if target.stat().st_size > 8192:
            return None
        data = json.loads(target.read_text(encoding="utf-8"))
        if (data.get("schema_version") != 1
                or data.get("source") != "OWNER_AUTHORIZED_DEMO_READ"
                or data.get("execution_enabled") is not False
                or data.get("reconciliation_status") not in ("MATCHED", "DISCREPANCY")
                or not isinstance(data.get("books"), list)
                or len(data["books"]) != 3):
            return None
        observed = datetime.fromisoformat(data["observed_at"])
        current = now or datetime.now(timezone.utc)
        if observed.tzinfo is None or not timedelta(0) <= current - observed <= timedelta(minutes=5):
            return None
        # Strict field allowlist: never emit arbitrary persisted values into browser JSON.
        return {
            "observed_at": observed.isoformat(),
            "reconciliation_status": data["reconciliation_status"],
            "discrepancy_count": data["discrepancy_count"] if type(data.get("discrepancy_count")) is int and data["discrepancy_count"] >= 0 else None,
            "available_cash_usd_status": data["available_cash_usd_status"] if data.get("available_cash_usd_status") in ("AVAILABLE", "UNAVAILABLE") else "UNAVAILABLE",
            "unrealized_pnl_status": data["unrealized_pnl_status"] if data.get("unrealized_pnl_status") in ("AVAILABLE", "UNAVAILABLE") else "UNAVAILABLE",
            "books": [
                {"id": book, "positions": next((v["positions"] for v in data["books"] if isinstance(v, dict) and v.get("id") == book and type(v.get("positions")) is int and v["positions"] >= 0), None),
                 "allocation_status": "NOT_ALLOCATED"}
                for book in ("etoro-demo:tradingagents", "etoro-demo:ai-trading", "etoro-demo:unattributed")
            ],
        }
    except (OSError, ValueError, KeyError, TypeError):
        return None


def dashboard_summary(db_path: str, snapshot_path: str | None = None, *, now: datetime | None = None) -> dict[str, Any]:
    baseline = baseline_summary(db_path)
    fresh = read_refresh(snapshot_path, now=now)
    return {"schema_version": 1, "source": "LOCAL_BASELINE_ONLY",
            **baseline, "fresh_snapshot": fresh, "reconciliation_status": "NOT_CURRENT",
            "discrepancy_count": None, "available_cash_usd_status": "UNAVAILABLE",
            "unrealized_pnl_status": "UNAVAILABLE", "execution_enabled": False,
            "books": [
                {"id": "etoro-demo:tradingagents", "positions": None, "allocation_status": "NOT_ALLOCATED"},
                {"id": "etoro-demo:ai-trading", "positions": None, "allocation_status": "NOT_ALLOCATED"},
                {"id": "etoro-demo:unattributed", "positions": baseline["protected_positions"],
                 "allocation_status": "NOT_ALLOCATED"},
            ]}


def research_summary(path: str | None) -> dict[str, Any]:
    """Return a sanitized local research-status document for the dashboard."""
    base = {"schema_version": 1, "source": "LOCAL_RESEARCH_EVIDENCE",
            "status": "BLOCKED", "execution_enabled": False, "agents": [],
            "valuation": "PENDING", "broker_execution": "DISABLED"}
    if not path:
        return base
    target = Path(path)
    if not target.is_file() or target.is_symlink() or target.stat().st_size > 32768:
        return base
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        if data.get("schema_version") != 1 or data.get("execution_enabled") is not False:
            return base
        agents = [{"id": str(item["id"]), "status": str(item["status"]),
                   "evidence_count": int(item.get("evidence_count", 0))}
                  for item in data.get("agents", []) if isinstance(item, dict)
                  and item.get("id") in ("tradingagents", "ai-trading")
                  and item.get("status") in ("VERIFIED_OFFLINE", "BLOCKED", "NOT_RUN")
                  and type(item.get("evidence_count", 0)) is int and item["evidence_count"] >= 0]
        return {**base, "status": data.get("status") if data.get("status") in ("READY_OFFLINE", "BLOCKED") else "BLOCKED",
                "agents": agents, "valuation": data.get("valuation") if data.get("valuation") in ("VALIDATED", "PENDING", "BLOCKED") else "PENDING"}
    except (OSError, ValueError, KeyError, TypeError):
        return base


def strategy_catalogue_summary() -> dict[str, Any]:
    """Expose only versioned proposal metadata; no results or positions."""
    return {
        "schema_version": 1, "source": "LOCAL_STRATEGY_CATALOGUE",
        "execution_enabled": False, "status": "RESEARCH_ONLY",
        "strategies": [
            {"id": item.strategy_id, "version": item.version,
             "parameters": dict(item.parameters),
             "holding_period": [item.holding_period_min, item.holding_period_max],
             "execution_assumption": item.execution_assumption,
             "acceptance": "NOT_ASSESSED"}
            for item in catalogue()
        ],
        "broker_execution": "DISABLED",
    }


def _read_benchmark_audits(paths: tuple[str, ...]) -> dict[str, dict[str, Any]]:
    audits: dict[str, dict[str, Any]] = {}
    for raw_path in paths:
        target = Path(raw_path)
        if not target.is_file() or target.is_symlink() or target.stat().st_size > 128_000:
            continue
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
            ticker = data.get("ticker")
            benchmark = data.get("benchmark", {})
            if (ticker not in ("SPY", "QQQ", "MSFT") or data.get("broker_execution") != "DISABLED"
                    or not isinstance(benchmark, dict)):
                continue
            audits[ticker] = {
                "convention": benchmark.get("convention") if isinstance(benchmark.get("convention"), str) else "UNAVAILABLE",
                "total_return": benchmark.get("total_return") if benchmark.get("total_return") in ("UNAVAILABLE", "AVAILABLE") else "UNAVAILABLE",
                "ending_equity": benchmark.get("ending_equity") if isinstance(benchmark.get("ending_equity"), str) else None,
                "return": benchmark.get("return") if isinstance(benchmark.get("return"), str) else None,
                "max_drawdown": benchmark.get("max_drawdown") if isinstance(benchmark.get("max_drawdown"), str) else None,
                "corporate_action_status": data.get("corporate_action_status") if data.get("corporate_action_status") in ("VERIFIED", "NOT_ASSESSED", "REVIEW_REQUIRED") else "NOT_ASSESSED",
            }
        except (OSError, ValueError, TypeError, KeyError):
            continue
    return audits


def strategy_validation_summary(paths: tuple[str, ...] = (), audit_paths: tuple[str, ...] = ()) -> dict[str, Any]:
    """Expose sanitized local SD-021 metrics without equity paths or positions."""
    result: dict[str, Any] = {
        "schema_version": 1, "source": "LOCAL_STRATEGY_VALIDATION",
        "status": "NOT_LOADED", "execution_enabled": False, "datasets": [],
        "broker_execution": "DISABLED",
    }
    benchmark_audits = _read_benchmark_audits(audit_paths)
    for raw_path in paths:
        target = Path(raw_path)
        if not target.is_file() or target.is_symlink() or target.stat().st_size > 512_000:
            continue
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
            if data.get("schema_version") != 1 or data.get("broker_execution") != "DISABLED":
                continue
            metrics = ("annualized_return", "max_drawdown", "profit_factor", "sharpe",
                       "trade_count", "round_trip_count", "win_rate", "out_of_sample_days")
            strategies = []
            for strategy_id, evaluation in data.get("strategies", {}).items():
                if not isinstance(strategy_id, str) or not isinstance(evaluation, dict):
                    continue
                source_metrics = evaluation.get("metrics", {})
                strategies.append({
                    "id": strategy_id,
                    "status": data.get("acceptance", {}).get(strategy_id, {}).get("status", "NOT_ASSESSED"),
                    "metrics": {key: source_metrics.get(key) for key in metrics},
                })
            dataset = data.get("data", {})
            result["datasets"].append({
                "ticker": data.get("ticker"), "instrument_id": data.get("instrument_id"),
                "start": dataset.get("start"), "end": dataset.get("end"),
                "observations": dataset.get("observations"), "provenance": dataset.get("provenance"),
                "feed": dataset.get("feed"), "adjustment": dataset.get("adjustment"),
                "source_bundle_sha256": data.get("source_bundle_sha256"),
                "strategies": strategies,
                "portfolio": {key: data.get("portfolio", {}).get(key)
                              for key in ("ending_equity", "max_drawdown", "correlation_status")},
                "benchmark": benchmark_audits.get(str(data.get("ticker")), {
                    "convention": "UNAVAILABLE", "total_return": "UNAVAILABLE",
                    "ending_equity": None, "return": None, "max_drawdown": None,
                    "corporate_action_status": "NOT_ASSESSED",
                }),
            })
        except (OSError, ValueError, TypeError, KeyError):
            continue
    if result["datasets"]:
        result["status"] = "RESEARCH_ONLY"
    return result


def release_gate_summary(path: str | None = None) -> dict[str, Any]:
    """Expose only the fail-closed SD-030 paper-release decision."""
    base: dict[str, Any] = {
        "schema_version": 1,
        "source": "LOCAL_PAPER_RELEASE_GATE",
        "gate": "PAPER_RELEASE",
        "overall_status": "NO_GO",
        "engineering_rehearsal": "UNAVAILABLE",
        "release_enabled": False,
        "paper_order_submission": "DISABLED",
        "human_approval": "REQUIRED_SEPARATE_OWNER_RELEASE",
        "account_mapping": "UNVERIFIED",
        "broker_reconciliation": "UNRELEASED",
        "kill_switch": "UNRELEASED",
        "protected_baseline": "PRESERVED",
        "blocking_controls": ["RELEASE_GATE_NOT_LOADED"],
        "rehearsal": {"status": "UNAVAILABLE", "broker_execution": "DISABLED"},
        "broker_execution": "DISABLED",
        # Always code-derived; a local file can never override broker status.
        "etoro_demo": etoro_demo_status(),
    }
    if not path:
        return base
    target = Path(path)
    if not target.is_file() or target.is_symlink() or target.stat().st_size > 32768:
        return base
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        if (data.get("schema_version") != 1 or data.get("gate") != "PAPER_RELEASE"
                or data.get("overall_status") != "NO_GO"
                or data.get("release_enabled") is not False
                or data.get("paper_order_submission") != "DISABLED"
                or data.get("broker_execution") not in (None, "DISABLED")):
            return base
        blocking = data.get("blocking_controls")
        rehearsal = data.get("rehearsal")
        if (not isinstance(blocking, list) or not all(isinstance(item, str) for item in blocking)
                or not isinstance(rehearsal, dict)
                or rehearsal.get("broker_execution") != "DISABLED"):
            return base
        return {
            **base,
            "engineering_rehearsal": data.get("engineering_rehearsal") if data.get("engineering_rehearsal") == "PASS" else "UNAVAILABLE",
            "blocking_controls": sorted(set(blocking)) or ["RELEASE_GATE_NOT_LOADED"],
            "rehearsal": {
                "status": rehearsal.get("status") if rehearsal.get("status") == "REHEARSED" else "UNAVAILABLE",
                "broker_execution": "DISABLED",
                "final_state": rehearsal.get("final_state") if isinstance(rehearsal.get("final_state"), str) else None,
                "event_count": rehearsal.get("event_count") if type(rehearsal.get("event_count")) is int and rehearsal["event_count"] >= 0 else None,
            },
        }
    except (OSError, ValueError, TypeError, KeyError):
        return base


def make_handler(db_path: str, snapshot_path: str | None = None, research_path: str | None = None,
                 strategy_paths: tuple[str, ...] = (), audit_paths: tuple[str, ...] = (),
                 release_gate_path: str | None = None, universe_path: str | None = None,
                 pilot_path: str | None = None,
                 scan_path: str | None = None, authorization_ledger: str | None = None,
                 ledger_dir: str | None = None, uk_data_dir: str | None = None,
                 uk_report: str | None = None, *,
                 pipeline_report: str | None = "data/sd103/latest-run.json",
                 pipeline_history: str | None = "data/sd109/run-history.sqlite3",
                 day_trader_runs: str = "data/day-trader-runs.sqlite3"
                 ) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.headers.get("Host") not in ("127.0.0.1:8765", "localhost:8765") or urlsplit(self.path).query:
                self.send_error(404)
                return
            try:
                route = urlsplit(self.path).path
                if route == "/api/demo/summary":
                    data = dashboard_summary(db_path, snapshot_path)
                elif route == "/api/research/summary":
                    data = research_summary(research_path)
                elif route == "/api/research/strategies":
                    data = strategy_catalogue_summary()
                elif route == "/api/research/validation":
                    data = strategy_validation_summary(strategy_paths, audit_paths)
                elif route == "/api/research/release-gate":
                    data = release_gate_summary(release_gate_path)
                elif route == "/api/market/tracks":
                    data = market_tracks_summary(universe_path, pilot_path)
                elif route == "/api/market/scan":
                    data = scan_snapshot_summary(scan_path)
                elif route == "/api/ops/authorizations":
                    data = authorization_ledger_summary(authorization_ledger)
                elif route == "/api/portfolio/ledgers":
                    data = track_ledgers_summary(ledger_dir)
                elif route == "/api/market/uk":
                    data = uk_markets_summary(uk_data_dir, uk_report)
                elif route == "/api/pipeline/latest":
                    data = pipeline_summary(pipeline_report)
                elif route == "/api/pipeline/history":
                    data = history_summary(pipeline_history)
                elif route == "/api/day-trader/summary":
                    data = day_trader_summary(day_trader_runs)
                else:
                    self.send_error(404)
                    return
                payload = json.dumps(data).encode("utf-8")
                status = 200
            except (OSError, sqlite3.Error, ValueError):
                payload = b'{"error":"BASELINE_UNAVAILABLE"}'
                status = 503
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_POST(self) -> None:
            self.send_error(405)

        def log_message(self, format: str, *args: Any) -> None:
            pass

    return Handler


def main() -> int:
    p = argparse.ArgumentParser(description="Local-only read-only eToro baseline summary")
    p.add_argument("--db", required=True)
    p.add_argument("--snapshot", default=None)
    p.add_argument("--research", default=None)
    p.add_argument("--strategy-research", action="append", default=[])
    p.add_argument("--strategy-audit", action="append", default=[])
    p.add_argument("--release-gate", default=None)
    p.add_argument("--universe-summary", default=None)
    p.add_argument("--price-pilot-summary", default=None)
    p.add_argument("--scan-snapshot", default=None)
    p.add_argument("--authorization-ledger", default="data/data-authorization-ledger.sqlite3")
    p.add_argument("--simulation-ledgers", default=None)
    p.add_argument("--uk-data-dir", default="data/uk")
    p.add_argument("--uk-report", default="data/uk-acceptance.json")
    p.add_argument("--pipeline-report", default="data/sd103/latest-run.json")
    p.add_argument("--pipeline-history", default="data/sd109/run-history.sqlite3")
    p.add_argument("--day-trader-runs", default="data/day-trader-runs.sqlite3")
    a = p.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", 8765), make_handler(a.db, a.snapshot, a.research,
                                                                     tuple(a.strategy_research), tuple(a.strategy_audit), a.release_gate,
                                                                     a.universe_summary, a.price_pilot_summary,
                                                                     a.scan_snapshot, a.authorization_ledger,
                                                                     a.simulation_ledgers, a.uk_data_dir,
                                                                     a.uk_report,
                                                                     pipeline_report=a.pipeline_report,
                                                                     pipeline_history=a.pipeline_history,
                                                                     day_trader_runs=a.day_trader_runs))
    print("SideDeck baseline API listening on 127.0.0.1:8765 (read-only)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
