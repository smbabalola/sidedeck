"""Opt-in XNYS close schedule for the Day Trader's offline fixture research run.

This adapter reuses SD-068's durable slot/lease/restart behavior. It runs only pinned fixtures,
requires an explicit acceptance flag, and never uses external data or an execution route.
"""
from __future__ import annotations

import argparse
import json
import socket
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sidedeck.application.sd068_track_scheduler import Cadence, JobSpec, SchedulerStore
from sidedeck.application.sd114_day_trader_runs import RunStore, _fixture_inputs
from sidedeck.modules.day_trader.orchestrator import DayTraderConfig, run_module

JOB_ID = "day_trader_fixture_research"
JOB = JobSpec(JOB_ID, "DAY", "Day Trader offline fixture research after XNYS close",
              Cadence(offsets=(("CLOSE", 45),)), lease_seconds=1800,
              max_lateness_seconds=18 * 3600)


def _record(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, isolation_level=None)) as conn:
        conn.executescript("""CREATE TABLE IF NOT EXISTS sd121_schedule_audit (
            slot TEXT PRIMARY KEY, completed_at TEXT NOT NULL, status TEXT NOT NULL,
            run_id TEXT, basis TEXT NOT NULL, report_sha256 TEXT, reason TEXT);
            CREATE TRIGGER IF NOT EXISTS sd121_schedule_no_update BEFORE UPDATE
            ON sd121_schedule_audit BEGIN SELECT RAISE(ABORT, 'append-only schedule audit'); END;
            CREATE TRIGGER IF NOT EXISTS sd121_schedule_no_delete BEFORE DELETE
            ON sd121_schedule_audit BEGIN SELECT RAISE(ABORT, 'append-only schedule audit'); END;""")
        conn.execute("INSERT INTO sd121_schedule_audit VALUES (?,?,?,?,?,?,?)", (
            row["slot"], row["completed_at"], row["status"], row.get("run_id"),
            row["basis"], row.get("report_sha256"), row.get("reason"),
        ))


def tick(*, now: datetime, schedule_db: Path, runs_db: Path, audit_db: Path,
         fixture_acceptance: bool = False, owner: str | None = None) -> dict[str, Any]:
    """Run one due scheduled fixture job; slots and reports survive process restarts."""
    if fixture_acceptance is not True:
        raise PermissionError("scheduled fixture research requires fixture_acceptance=True")
    if now.tzinfo is None:
        raise ValueError("timezone-aware schedule time required")
    db_paths = {path.resolve() for path in (schedule_db, runs_db, audit_db)}
    if len(db_paths) != 3:
        raise ValueError("scheduler, run ledger and audit ledger must use separate SQLite files")
    store = SchedulerStore(schedule_db, (JOB,))
    store.set_track("DAY", enabled=True, mode="SIMULATION_ONLY")
    store.set_exchange_track("XNYS", "DAY", enabled=True, mode="SIMULATION_ONLY")
    due = [item for item in store.due(now) if item.job_id == JOB_ID]
    if not due:
        return {"status": "NOT_DUE", "broker_execution": "DISABLED"}
    slot = due[-1].slot
    holder = owner or f"{socket.gethostname()}:sd121"
    claim = store.claim(JOB_ID, slot, holder, now)
    if not claim.claimed:
        return {"status": "NOT_CLAIMED", "reason": claim.reason, "slot": slot.isoformat()}
    run_id: str | None = None
    digest: str | None = None
    reason: str | None = None
    status = "FAILED"
    basis = "UNKNOWN"
    try:
        report = run_module(_fixture_inputs(), DayTraderConfig(mode="SIMULATION_ONLY"))
        basis = str(report.get("data_basis", "UNKNOWN"))
        store_runs = RunStore(runs_db)
        try:
            run_id = store_runs.save(report)
            saved = store_runs.latest()
            digest = str(saved["report_sha256"]) if saved else None
        finally:
            store_runs.close()
        status = "COMPLETED"
    except Exception as exc:  # noqa: BLE001 - failures are recorded and the slot is finished
        reason = f"{type(exc).__name__}: {exc}"[:300]
    completed_at = datetime.now(UTC).isoformat()
    _record(audit_db, {"slot": slot.isoformat(), "completed_at": completed_at,
                       "status": status, "run_id": run_id, "basis": basis,
                       "report_sha256": digest, "reason": reason})
    store.finish(JOB_ID, slot, holder, max(now, datetime.now(UTC)), ok=status == "COMPLETED")
    return {"status": status, "slot": slot.isoformat(), "run_id": run_id,
            "basis": basis, "report_sha256": digest, "reason": reason,
            "broker_execution": "DISABLED"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Tick the opt-in offline Day Trader fixture schedule")
    parser.add_argument("--fixture-acceptance", action="store_true")
    parser.add_argument("--schedule-db", type=Path, default=Path("data/day-trader-schedule.sqlite3"))
    parser.add_argument("--runs-db", type=Path, default=Path("data/day-trader-runs.sqlite3"))
    parser.add_argument("--audit-db", type=Path, default=Path("data/day-trader-schedule-audit.sqlite3"))
    args = parser.parse_args(argv)
    result = tick(now=datetime.now(UTC), schedule_db=args.schedule_db, runs_db=args.runs_db,
                  audit_db=args.audit_db, fixture_acceptance=args.fixture_acceptance)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
