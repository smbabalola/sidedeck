"""SD-109 research-only SD-103 pipeline runs after each US market close.

No daemon. ``tick`` is meant to be called periodically (e.g. Windows Task Scheduler every
30 minutes). It reuses the SD-068 ``SchedulerStore`` (persisted slots, leases, overlap and
duplicate refusal, missed-slot coalescing) with one job, ``pipeline_research_run``, 45
minutes after each XNYS close (early closes honoured by the XNYS calendar). A due run calls
the SD-103 ``run`` mode only: research and decisions, order intents never submitted, broker
route ``SIMULATED_LOCAL``.

Each run is recorded in a run-history table with the data freshness verdict (latest bar
session vs the scheduled session), the decision summary, the NO TRADE explanation, the report
path and its SHA-256. Stale data is recorded as ``STALE_DATA`` (the run still documents the
decision, which the decision engine itself rejects on staleness); a failure is recorded as
``FAILED`` with the reason. Nothing here fetches market data or contacts a broker: fresh bars
arrive only through separately authorized data runs (SD-075B/SD-077).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import socket
import sqlite3
from collections.abc import Callable
from contextlib import closing
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from sidedeck.application.sd068_track_scheduler import Cadence, JobSpec, SchedulerStore
from sidedeck.application.sd089_exchange_calendar import XNYS

JOB_ID = "pipeline_research_run"
JOB = JobSpec(JOB_ID, "SWING", "SD-103 research-only pipeline run after the XNYS close",
              Cadence(offsets=(("CLOSE", 45),)), lease_seconds=1800,
              max_lateness_seconds=18 * 3600)
STATUSES = ("COMPLETED", "STALE_DATA", "FAILED")
DATA_DIR = Path(__file__).resolve().parents[3] / "data"

PipelineRunner = Callable[[], tuple[dict[str, Any], Path]]


class ScheduleError(RuntimeError):
    pass


class RunHistory:
    """Append-only evidence for each scheduled pipeline run (one row per slot)."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        with closing(sqlite3.connect(path, isolation_level=None)) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS sd109_runs (
                  slot TEXT PRIMARY KEY, session TEXT NOT NULL, started_at TEXT NOT NULL,
                  finished_at TEXT NOT NULL, status TEXT NOT NULL, latest_bar_session TEXT,
                  freshness TEXT NOT NULL, decisions TEXT NOT NULL, orders INTEGER NOT NULL,
                  no_trade TEXT, report_path TEXT, report_sha256 TEXT, reason TEXT);
                CREATE TRIGGER IF NOT EXISTS sd109_no_update BEFORE UPDATE ON sd109_runs
                  BEGIN SELECT RAISE(ABORT, 'append-only run history'); END;
                CREATE TRIGGER IF NOT EXISTS sd109_no_delete BEFORE DELETE ON sd109_runs
                  BEGIN SELECT RAISE(ABORT, 'append-only run history'); END;""")

    def record(self, row: dict[str, Any]) -> None:
        with closing(sqlite3.connect(self._path, isolation_level=None)) as conn:
            conn.execute("INSERT INTO sd109_runs VALUES (:slot,:session,:started_at,:finished_at,"
                         ":status,:latest_bar_session,:freshness,:decisions,:orders,:no_trade,"
                         ":report_path,:report_sha256,:reason)", row)

    def rows(self, limit: int = 60) -> list[dict[str, Any]]:
        with closing(sqlite3.connect(self._path)) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(r) for r in conn.execute(
                "SELECT * FROM sd109_runs ORDER BY slot DESC LIMIT ?", (limit,))]


def freshness(latest_bar: date | None, session: date) -> str:
    if latest_bar is None:
        return "NO_DATA"
    if latest_bar > session:
        return "FUTURE_BAR_REFUSED"
    if latest_bar == session:
        return "CURRENT"
    missing = len(XNYS.sessions_between(latest_bar, session)) - 1
    return f"STALE_{missing}_SESSIONS"


def tick(*, now: datetime, store: SchedulerStore, history: RunHistory,
         runner: PipelineRunner, owner: str | None = None) -> dict[str, Any]:
    """Run the pipeline once if a post-close slot is due; otherwise report why not."""
    if now.tzinfo is None:
        raise ScheduleError("timezone-aware time required")
    due = [d for d in store.due(now) if d.job_id == JOB_ID]
    if not due:
        return {"status": "NOT_DUE", "next_slot": next_slot(now).isoformat()}
    slot = due[-1].slot
    holder = owner or f"{socket.gethostname()}:sd109"
    claim = store.claim(JOB_ID, slot, holder, now)
    if not claim.claimed:
        return {"status": "NOT_CLAIMED", "reason": claim.reason, "slot": slot.isoformat()}
    session = XNYS.local_date(slot)
    started = now.astimezone(UTC).isoformat()
    row: dict[str, Any] = {"slot": slot.isoformat(), "session": session.isoformat(),
                           "started_at": started, "latest_bar_session": None,
                           "decisions": "{}", "orders": 0, "no_trade": None,
                           "report_path": None, "report_sha256": None, "reason": None}
    ok = False
    try:
        report, path = runner()
        latest = date.fromisoformat(report["data_freshness"]["latest_session"])
        fresh = freshness(latest, session)
        counts: dict[str, int] = {}
        for d in report.get("decisions", []):
            counts[d["decision"]] = counts.get(d["decision"], 0) + 1
        row.update(status=("COMPLETED" if fresh == "CURRENT" else "FAILED"
                           if fresh == "FUTURE_BAR_REFUSED" else "STALE_DATA"),
                   latest_bar_session=latest.isoformat(), freshness=fresh,
                   decisions=json.dumps(counts, sort_keys=True),
                   orders=len(report.get("orders", [])), no_trade=report.get("no_trade"),
                   report_path=str(path),
                   report_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        ok = row["status"] != "FAILED"
    except BaseException as exc:  # noqa: BLE001 - recorded (even on interrupt), then finish
        row.update(status="FAILED", freshness="UNKNOWN",
                   reason=f"{type(exc).__name__}: {exc}"[:300])
        if not isinstance(exc, Exception):
            _close(history, store, row, slot, holder, now, ok=False)
            raise
    _close(history, store, row, slot, holder, now, ok=ok)
    return {"status": row["status"], "slot": row["slot"], "freshness": row["freshness"],
            "orders": row["orders"], "report": row["report_path"], "reason": row["reason"]}


def _close(history: RunHistory, store: SchedulerStore, row: dict[str, Any], slot: datetime,
           holder: str, now: datetime, *, ok: bool) -> None:
    row["finished_at"] = datetime.now(UTC).isoformat()
    try:
        history.record(row)
    finally:
        store.finish(JOB_ID, slot, holder, max(now, datetime.now(UTC)), ok=ok)


def next_slot(now: datetime) -> datetime:
    day = XNYS.local_date(now)
    for _ in range(10):
        session = XNYS.session(day)
        if session is not None:
            slot = session.close_utc + timedelta(minutes=45)
            if slot > now:
                return slot
        day += timedelta(days=1)
    raise ScheduleError("no XNYS session within ten days")


def history_summary(path: str | None) -> dict[str, Any]:
    """Read-only projection for the dashboard (``/api/pipeline/history``)."""
    target = Path(path) if path else None
    base = {"schema_version": 1, "execution_enabled": False, "job": JOB_ID,
            "cadence": "45 minutes after each XNYS close; research only"}
    if target is None or not target.is_file():
        return {**base, "status": "NOT_STARTED", "runs": []}
    try:      # read-only: no directory creation, no DDL, from the dashboard
        with closing(sqlite3.connect(target.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            rows = [dict(r) for r in conn.execute(
                "SELECT * FROM sd109_runs ORDER BY slot DESC LIMIT 60")]
    except sqlite3.Error:
        return {**base, "status": "UNAVAILABLE", "runs": []}
    keep = ("slot", "session", "status", "latest_bar_session", "freshness", "orders",
            "no_trade", "report_sha256", "reason", "finished_at")
    runs = []
    for r in rows:
        item: dict[str, Any] = {k: (None if r[k] is None else str(r[k])[:240]) for k in keep}
        item["orders"] = int(r["orders"])
        try:
            item["decisions"] = {str(k)[:20]: int(v) for k, v in json.loads(r["decisions"]).items()}
        except (ValueError, TypeError, AttributeError):
            item["decisions"] = {}
        runs.append(item)
    try:
        upcoming = next_slot(datetime.now(UTC)).isoformat()
    except Exception:  # noqa: BLE001 - calendar coverage ends; shown as unknown
        upcoming = None
    return {**base, "status": "ACTIVE" if runs else "NO_RUNS_YET", "next_slot": upcoming,
            "runs": runs}


def main(argv: list[str] | None = None) -> int:
    from sidedeck.application import sd103_trading_pipeline as sd103

    parser = argparse.ArgumentParser(description="SD-109 research-only scheduled pipeline run")
    parser.add_argument("command", choices=("tick", "history"))
    parser.add_argument("--root", default=str(DATA_DIR / "sd109"))
    args = parser.parse_args(argv)
    root = Path(args.root)
    history = RunHistory(root / "run-history.sqlite3")
    if args.command == "history":
        print(json.dumps(history_summary(str(root / "run-history.sqlite3")), indent=2))
        return 0
    store = SchedulerStore(root / "scheduler.sqlite3", jobs=(JOB,))

    def runner() -> tuple[dict[str, Any], Path]:
        bundles = [sd103.load_bundle(DATA_DIR / f"sd021-{t}-admitted.json")
                   for t in ("spy", "qqq", "msft")]
        cfg = sd103.PipelineConfig(broker_mappings=sd103._default_mappings(DATA_DIR))
        ctx, excluded = sd103.build_context(bundles, basis=sd103.REAL_DATA,
                                            admission_through=date(2026, 12, 31), cfg=cfg)
        report = sd103.run_report(ctx, excluded, now=datetime.now(UTC), mode="run")
        return report, sd103.write_report(report, DATA_DIR / "sd103")

    print(json.dumps(tick(now=datetime.now(UTC), store=store, history=history, runner=runner),
                     indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
