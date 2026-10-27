"""Durable, read-only-facing Day Trader research runs and offline CLI.

The store is a local append-only evidence ledger for sanitized orchestrator reports. It never
stores credentials or broker state and never changes the module's RESEARCH_ONLY mode.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sidedeck.modules.day_trader.manifest import SOURCE_VERSION, UPSTREAM
from sidedeck.modules.day_trader.orchestrator import (
    DayTraderConfig, Inputs, run_module, upstream_fixture_inputs,
)
from sidedeck.modules.day_trader.research import load_owner_csv, orb_backtest

SCHEMA = "sidedeck-day-trader-run-ledger/1"
MAX_REPORT_BYTES = 8_000_000


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _derived(report: dict[str, Any]) -> dict[str, Any]:
    raw_plans = report.get("plans")
    plans: list[Any] = raw_plans if isinstance(raw_plans, list) else []
    raw_scan = report.get("scan")
    opportunities: list[Any] = raw_scan.get("hits", []) if isinstance(raw_scan, dict) and isinstance(raw_scan.get("hits"), list) else []
    rejected = [{"symbol": p.get("symbol"), "result": p.get("result"),
                 "reason": p.get("entry", {}).get("reason") if isinstance(p.get("entry"), dict) else ""}
                for p in plans if isinstance(p, dict) and p.get("result") not in ("SKILL_RISK_PASS",)]
    raw_stages = report.get("stages")
    stages: list[Any] = raw_stages if isinstance(raw_stages, list) else []
    errors = [{"stage": s.get("stage"), "skill": s.get("skill"), "status": s.get("status"),
               "reason": s.get("reason", "")}
              for s in stages if isinstance(s, dict)
              and s.get("status") not in ("OK", "SKIPPED")]
    simulation = report.get("simulation", {}) if isinstance(report.get("simulation"), dict) else {}
    return {"opportunities": opportunities[:100], "plans": plans[:50],
            "simulations": simulation, "rejected": rejected[:100], "errors": errors[:100]}


class RunStore:
    """SQLite store with immutable run rows and bounded result reads."""

    def __init__(self, path: Path, *, read_only: bool = False) -> None:
        self.path = path.resolve()
        if read_only:
            self.db = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.db = sqlite3.connect(path)
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("""CREATE TABLE IF NOT EXISTS day_trader_runs (
            run_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, basis TEXT NOT NULL,
            mode TEXT NOT NULL, status TEXT NOT NULL, module_version TEXT NOT NULL,
            source_commit TEXT NOT NULL, report_sha256 TEXT NOT NULL,
            report_json TEXT NOT NULL, derived_json TEXT NOT NULL
            )""")
            self.db.executescript("""CREATE TRIGGER IF NOT EXISTS day_trader_runs_no_update
            BEFORE UPDATE ON day_trader_runs BEGIN
              SELECT RAISE(ABORT, 'Day Trader run ledger is append-only');
            END;
            CREATE TRIGGER IF NOT EXISTS day_trader_runs_no_delete
            BEFORE DELETE ON day_trader_runs BEGIN
              SELECT RAISE(ABORT, 'Day Trader run ledger is append-only');
            END;""")
            self.db.commit()

    def close(self) -> None:
        self.db.close()

    def save(self, report: dict[str, Any]) -> str:
        raw = _json(report).encode("utf-8")
        if len(raw) > MAX_REPORT_BYTES:
            raise ValueError("Day Trader report exceeds the bounded persistence limit")
        digest = hashlib.sha256(raw).hexdigest()
        created = datetime.now(UTC).isoformat()
        run_id = uuid.uuid4().hex[:24]
        self.db.execute("""INSERT INTO day_trader_runs
            (run_id, created_at, basis, mode, status, module_version, source_commit,
             report_sha256, report_json, derived_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (run_id, created, str(report.get("data_basis", "UNKNOWN")), str(report.get("mode", "UNKNOWN")),
             str(report.get("status", "UNKNOWN")), SOURCE_VERSION, UPSTREAM["commit"], digest,
             raw.decode("utf-8"), _json(_derived(report))))
        self.db.commit()
        return run_id

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 50))
        rows = self.db.execute("""SELECT run_id, created_at, basis, mode, status, module_version,
            source_commit, report_sha256 FROM day_trader_runs
            ORDER BY created_at DESC, run_id DESC LIMIT ?""", (limit,))
        return [{"run_id": r[0], "created_at": r[1], "basis": r[2], "mode": r[3], "status": r[4],
                 "module_version": r[5], "source_commit": r[6], "report_sha256": r[7]} for r in rows]

    def latest(self) -> dict[str, Any] | None:
        row = self.db.execute("""SELECT run_id, created_at, basis, mode, status, module_version,
            source_commit, report_sha256, derived_json FROM day_trader_runs
            ORDER BY created_at DESC, run_id DESC LIMIT 1""").fetchone()
        if row is None:
            return None
        result = json.loads(row[8])
        return {"run_id": row[0], "created_at": row[1], "basis": row[2], "mode": row[3],
                "status": row[4], "module_version": row[5], "source_commit": row[6],
                "report_sha256": row[7], **result}


def day_trader_run_summary(path: str = "data/day-trader-runs.sqlite3") -> dict[str, Any]:
    """Sanitized dashboard payload; a missing ledger is an explicit empty state."""
    target = Path(path)
    if not target.is_file() or target.is_symlink():
        return {"schema_version": 1, "module": "DAY_TRADER", "book": "DAY_TRADER_SKILL",
                "mode": "RESEARCH_ONLY", "execution_enabled": False, "broker_execution": "DISABLED",
                "runs": [], "latest": None, "opportunities": [], "plans": [], "simulations": {},
                "rejected": [], "errors": [], "data_status": "NO_SAVED_RUN"}
    store = RunStore(target, read_only=True)
    try:
        latest = store.latest()
        return {"schema_version": 1, "module": "DAY_TRADER", "book": "DAY_TRADER_SKILL",
                "mode": "RESEARCH_ONLY", "execution_enabled": False, "broker_execution": "DISABLED",
                "runs": store.list_runs(), "latest": latest,
                "opportunities": latest["opportunities"] if latest else [],
                "plans": latest["plans"] if latest else [],
                "simulations": latest["simulations"] if latest else {},
                "rejected": latest["rejected"] if latest else [],
                "errors": latest["errors"] if latest else [],
                "data_status": "LOADED_FROM_LOCAL_RUN" if latest else "NO_SAVED_RUN"}
    finally:
        store.close()


def _fixture_inputs() -> Inputs:
    root = Path(__file__).resolve().parents[3] / "third_party" / "day-trader-skill"
    return upstream_fixture_inputs(root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the pinned Day Trader skill offline")
    parser.add_argument("run", choices=("run", "latest", "backtest-csv"))
    parser.add_argument("--db", default="data/day-trader-runs.sqlite3")
    parser.add_argument("--fixture", action="store_true", help="use the pinned labelled fixtures")
    parser.add_argument("--csv", type=Path, help="local five-minute CSV input for backtest-csv")
    parser.add_argument("--source-label", default="", help="operator-supplied source note (unverified)")
    parser.add_argument("--licence-reference", default="", help="operator-supplied rights note (unverified)")
    parser.add_argument("--target-r", default="2", help="positive target multiple for the ORB research backtest")
    args = parser.parse_args(argv)
    if args.run == "latest":
        print(_json(day_trader_run_summary(args.db)))
        return 0
    if args.run == "backtest-csv":
        if args.csv is None:
            parser.error("backtest-csv requires --csv")
        try:
            bars, provenance = load_owner_csv(
                args.csv, source_label=args.source_label, licence_reference=args.licence_reference,
            )
            report = orb_backtest(
                bars, target_r=Decimal(args.target_r), basis=provenance["basis"],
            )
        except (OSError, ValueError, ArithmeticError) as exc:
            parser.error(str(exc))
        print(_json({"schema": "sidedeck-day-trader-backtest/1", "provenance": provenance,
                     "mode": "RESEARCH_ONLY", "performance_status": "NOT_ASSESSED",
                     "strategy_admission": "BLOCKED", "broker_execution": "DISABLED",
                     "backtest": report}))
        return 0
    if not args.fixture:
        parser.error("run requires --fixture; genuine data needs a separately approved package")
    report = run_module(_fixture_inputs(), DayTraderConfig(mode="SIMULATION_ONLY"))
    store = RunStore(Path(args.db))
    try:
        run_id = store.save(report)
    finally:
        store.close()
    print(_json({"schema": SCHEMA, "run_id": run_id, "status": report["status"],
                 "basis": report["data_basis"], "stage_counts": report["stage_counts"],
                 "plans": len(report.get("plans", [])), "proposals": len(report.get("proposals", [])),
                 "broker_execution": "DISABLED"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
