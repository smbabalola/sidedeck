"""SD-152 first slice: restart-safe, single-writer OFFLINE SWING session worker.

Uses SD-068's pre-existing XNYS schedule and SD-140's real policy/SD-138 fake
order flow. The extra durable singleton fence intentionally has NO timeout
takeover: a crash or stale worker requires reconciliation rather than risking
a duplicate autonomous send. No background daemon, HTTP, .env or order release.
"""
from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Callable, Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sidedeck.application.sd063_autonomous_demo_policy import EntryProposal, Refusal
from sidedeck.application.sd068_track_scheduler import SchedulerStore
from sidedeck.application.sd074_trusted_inputs import Envelope
from sidedeck.application.sd140_offline_swing_controller import (
    OfflineSwingCycleController, SwingCycleResult,
)

SWING_JOB = "swing_review"
_FENCE_DDL = """
CREATE TABLE IF NOT EXISTS offline_swing_single_writer (
    id INTEGER PRIMARY KEY CHECK(id = 1),
    state TEXT NOT NULL CHECK(state IN ('IDLE','RUNNING','UNRESOLVED')),
    token TEXT NOT NULL, slot TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS offline_swing_runs (
    slot TEXT PRIMARY KEY, token TEXT NOT NULL UNIQUE,
    owner TEXT NOT NULL, state TEXT NOT NULL, started_at TEXT NOT NULL,
    finished_at TEXT
);
"""


class OfflineRunnerRefused(PermissionError):
    pass


@dataclass(frozen=True)
class RunnerOutcome:
    status: str
    slot: str | None
    detail: str
    cycle: SwingCycleResult | None = None
    execution_release: str = "ETORO_DEMO_NOT_RELEASED"

    def report(self) -> dict[str, Any]:
        return {
            "schema": "sidedeck.sd152.offline-swing-run/1",
            "status": self.status,
            "slot": self.slot,
            "detail": self.detail,
            "cycle": None if self.cycle is None else self.cycle.report(),
            "execution_release": self.execution_release,
        }


class OfflineSwingRunFence:
    """Cross-process at-most-once slot fence, fail-closed across process restarts."""

    def __init__(self, path: Path) -> None:
        self._path = path
        with closing(self._conn()) as conn:
            conn.executescript(_FENCE_DDL)
            conn.execute(
                "INSERT OR IGNORE INTO offline_swing_single_writer "
                "(id,state,token,slot,updated_at) VALUES(1,'IDLE','','','')",
            )

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path, isolation_level=None, timeout=30)

    def state(self) -> str:
        with closing(self._conn()) as conn:
            row = conn.execute(
                "SELECT state FROM offline_swing_single_writer WHERE id=1"
            ).fetchone()
        if row is None or row[0] not in {"IDLE", "RUNNING", "UNRESOLVED"}:
            raise OfflineRunnerRefused("single-writer durable fence is missing or corrupt")
        return str(row[0])

    def acquire(self, slot: datetime, *, owner: str, at: datetime) -> str | None:
        if not owner or not owner.strip() or len(owner) > 128:
            raise OfflineRunnerRefused("invalid worker identity")
        if slot.tzinfo is None or at.tzinfo is None:
            raise OfflineRunnerRefused("timezone-aware slot and clock required")
        iso_slot = slot.astimezone(UTC).isoformat()
        now = at.astimezone(UTC).isoformat()
        token = uuid.uuid4().hex
        with closing(self._conn()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                state = conn.execute(
                    "SELECT state FROM offline_swing_single_writer WHERE id=1"
                ).fetchone()
                if state is None or state[0] != "IDLE":
                    conn.execute("ROLLBACK")
                    return None
                if conn.execute(
                    "SELECT 1 FROM offline_swing_runs WHERE slot=?", (iso_slot,)
                ).fetchone():
                    conn.execute("ROLLBACK")
                    return None
                conn.execute(
                    "INSERT INTO offline_swing_runs VALUES(?,?,?,?,?,NULL)",
                    (iso_slot, token, owner, "RUNNING", now),
                )
                conn.execute(
                    "UPDATE offline_swing_single_writer SET state='RUNNING',"
                    "token=?,slot=?,updated_at=? WHERE id=1",
                    (token, iso_slot, now),
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return token

    def finish(self, token: str, *, at: datetime, safe: bool, outcome: str) -> None:
        if at.tzinfo is None:
            raise OfflineRunnerRefused("timezone-aware finish required")
        now = at.astimezone(UTC).isoformat()
        with closing(self._conn()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT state,token,slot FROM offline_swing_single_writer WHERE id=1"
                ).fetchone()
                if row is None or row[0] != "RUNNING" or row[1] != token:
                    raise OfflineRunnerRefused("worker has lost the durable leader fence")
                conn.execute(
                    "UPDATE offline_swing_runs SET state=?,finished_at=? "
                    "WHERE slot=? AND token=? AND state='RUNNING'",
                    (outcome, now, row[2], token),
                )
                conn.execute(
                    "UPDATE offline_swing_single_writer SET state=?,token='',"
                    "updated_at=? WHERE id=1",
                    ("IDLE" if safe else "UNRESOLVED", now),
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

    def history(self) -> tuple[tuple[str, str], ...]:
        with closing(self._conn()) as conn:
            rows = conn.execute(
                "SELECT slot,state FROM offline_swing_runs ORDER BY slot"
            ).fetchall()
        return tuple((str(slot), str(state)) for slot, state in rows)


class OfflineSwingScheduledService:
    """An explicit local tick, not an unattended network-capable background task.

    The scheduler must be configured SIMULATION_ONLY by the test/operator;
    its execution mode can NEVER be switched to broker execution.
    """

    def __init__(
        self, scheduler: SchedulerStore, fence: OfflineSwingRunFence,
        controller: OfflineSwingCycleController, *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if (type(scheduler) is not SchedulerStore
                or type(fence) is not OfflineSwingRunFence
                or type(controller) is not OfflineSwingCycleController
                or SWING_JOB not in scheduler.jobs):
            raise OfflineRunnerRefused("requires existing scheduler and exact offline SWING route")
        job = scheduler.jobs[SWING_JOB]
        if job.track != "SWING" or job.calendar_id != "XNYS":
            raise OfflineRunnerRefused("SWING schedule must use the US equity exchange")
        self.scheduler, self.fence, self.controller = scheduler, fence, controller
        self.clock = clock

    def run_due(
        self, *, owner: str,
        planning_bids: Sequence[Envelope] = (),
        execution_bids: Mapping[str, Envelope] | None = None,
        entry: EntryProposal | Refusal | None = None,
        entry_quote: Envelope | None = None,
        entry_marks: Sequence[Envelope] = (),
    ) -> RunnerOutcome:
        now = self.clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise OfflineRunnerRefused("worker clock must be timezone-aware")
        if self.fence.state() != "IDLE":
            return RunnerOutcome("RECOVERY_REQUIRED", None,
                                 "a prior worker is running or unresolved; no automatic takeover")
        job = self.scheduler.jobs[SWING_JOB]
        if self.scheduler.effective_mode(job) != "SIMULATION_ONLY":
            return RunnerOutcome("LOCKED", None, "explicit SIMULATION_ONLY mode required")
        due = [run for run in self.scheduler.due(now) if run.job_id == SWING_JOB]
        if not due:
            return RunnerOutcome("NO_DUE_SLOT", None, "no new eligible SWING schedule")
        slot = due[-1].slot
        token = self.fence.acquire(slot, owner=owner, at=now)
        if token is None:
            return RunnerOutcome("RECOVERY_REQUIRED", slot.isoformat(),
                                 "slot consumed or another worker holds the durable fence")
        claim = self.scheduler.claim(SWING_JOB, slot, owner, now)
        if not claim.claimed or claim.reason == "LEASE_TAKEOVER":
            # A prior scheduler lease cannot authorize another broker send.
            self.fence.finish(token, at=self.clock(), safe=False, outcome="CLAIM_REFUSED")
            return RunnerOutcome("RECOVERY_REQUIRED", slot.isoformat(),
                                 "scheduler claim refused or stale owner; reconcile manually")
        try:
            result = self.controller.tick(
                planning_bids=planning_bids, execution_bids=execution_bids,
                entry=entry, entry_quote=entry_quote, entry_marks=entry_marks,
            )
            success = result.status != "HALTED"
            self.fence.finish(token, at=self.clock(), safe=success, outcome=result.status)
            self.scheduler.finish(SWING_JOB, slot, owner, self.clock(), ok=success)
            return RunnerOutcome(
                result.status, slot.isoformat(), "OFFLINE_SIMULATOR_ONLY", result,
            )
        except Exception:
            # Do not retry this cycle or automatically take over an unknown
            # state; a crash before this block also leaves RUNNING durable.
            self.fence.finish(token, at=self.clock(), safe=False, outcome="EXCEPTION")
            self.scheduler.finish(SWING_JOB, slot, owner, self.clock(), ok=False)
            raise
