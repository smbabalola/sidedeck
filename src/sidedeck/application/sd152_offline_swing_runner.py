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


@dataclass(frozen=True)
class OfflineFenceHealth:
    """Read-only, audit-safe view; never grants or recovers trading authority."""

    state: str
    slot: str | None
    owner: str | None
    heartbeat_age_seconds: int | None
    alerts: tuple[str, ...]
    execution_release: str = "ETORO_DEMO_NOT_RELEASED"

    def report(self) -> dict[str, Any]:
        return {
            "schema": "sidedeck.sd152.offline-fence-health/1",
            "state": self.state, "slot": self.slot, "owner": self.owner,
            "heartbeat_age_seconds": self.heartbeat_age_seconds,
            "alerts": list(self.alerts),
            "broker_route": "SIMULATED_LOCAL",
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
                "SELECT state,token,slot FROM offline_swing_single_writer WHERE id=1"
            ).fetchone()
        if row is None or row[0] not in {"IDLE", "RUNNING", "UNRESOLVED"}:
            raise OfflineRunnerRefused("single-writer durable fence is missing or corrupt")
        if (row[0] == "IDLE" and row[1]
                or row[0] in {"RUNNING", "UNRESOLVED"} and not row[2]
                or row[0] == "RUNNING" and not row[1]):
            raise OfflineRunnerRefused("durable fence state and worker identity conflict")
        return str(row[0])

    def health(self, *, now: datetime, stale_after_seconds: int = 120) -> OfflineFenceHealth:
        """Read durable worker state only; stale RUNNING never becomes available.

        No SDK, credential, network, kill-switch reset or recovery authority.
        Corrupt state fails closed instead of being described as healthy.
        """
        if (now.tzinfo is None or now.utcoffset() is None
                or stale_after_seconds < 1):
            raise OfflineRunnerRefused("valid timezone-aware health clock required")
        with closing(self._conn()) as conn:
            row = conn.execute(
                "SELECT state,token,slot,updated_at FROM offline_swing_single_writer WHERE id=1"
            ).fetchone()
            if row is None or row[0] not in {"IDLE", "RUNNING", "UNRESOLVED"}:
                raise OfflineRunnerRefused("durable fence state missing or invalid")
            state, token, slot, updated_at = map(str, row)
            if (state == "IDLE" and token
                    or state in {"RUNNING", "UNRESOLVED"} and not slot
                    or state == "RUNNING" and not token):
                raise OfflineRunnerRefused("durable fence state and worker identity conflict")
            owner: str | None = None
            if state in {"RUNNING", "UNRESOLVED"}:
                if not token and state == "RUNNING":
                    raise OfflineRunnerRefused("RUNNING worker has no durable token")
                if slot:
                    worker = conn.execute(
                        "SELECT owner FROM offline_swing_runs WHERE slot=? AND token=?",
                        (slot, token),
                    ).fetchone()
                    if worker is None and state == "RUNNING":
                        raise OfflineRunnerRefused("RUNNING worker has no matching run record")
                    if worker is not None:
                        owner = str(worker[0])
            age: float | None
            try:
                moment = datetime.fromisoformat(updated_at)
                if moment.tzinfo is None or moment.utcoffset() is None:
                    raise ValueError("naive heartbeat")
                age = (now.astimezone(UTC) - moment.astimezone(UTC)).total_seconds()
            except ValueError:
                if state != "IDLE":
                    raise OfflineRunnerRefused("durable heartbeat cannot be verified") from None
                age = None
            alerts: list[str] = []
            if state == "RUNNING":
                alerts.append("EXCLUSIVE_WORKER_ACTIVE")
                if age is None or age < 0:
                    alerts.append("HEARTBEAT_CLOCK_UNVERIFIED")
                elif age > stale_after_seconds:
                    alerts.append("STALE_RUNNING_HEARTBEAT_RECONCILIATION_REQUIRED")
            if state == "UNRESOLVED":
                alerts.append("MANUAL_RECONCILIATION_REQUIRED_NO_AUTOMATIC_TAKEOVER")
            return OfflineFenceHealth(
                state, slot or None, owner,
                None if age is None or age < 0 else int(age),
                tuple(alerts),
            )

    def heartbeat(self, token: str, *, owner: str, at: datetime) -> None:
        """Refresh the held worker only; never take over or extend an order grant."""
        if (not token or not owner or at.tzinfo is None
                or at.utcoffset() is None):
            raise OfflineRunnerRefused("heartbeat identity and timezone-aware time required")
        now = at.astimezone(UTC)
        with closing(self._conn()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT state,token,slot,updated_at FROM offline_swing_single_writer WHERE id=1"
                ).fetchone()
                if row is None or row[0] != "RUNNING" or row[1] != token:
                    raise OfflineRunnerRefused("worker does not hold the durable fence")
                worker = conn.execute(
                    "SELECT owner,state FROM offline_swing_runs WHERE slot=? AND token=?",
                    (row[2], token),
                ).fetchone()
                if worker is None or worker[0] != owner or worker[1] != "RUNNING":
                    raise OfflineRunnerRefused("heartbeat worker identity or run state differs")
                previous = datetime.fromisoformat(str(row[3]))
                if previous.tzinfo is None or now < previous.astimezone(UTC):
                    raise OfflineRunnerRefused("heartbeat clock regressed")
                conn.execute(
                    "UPDATE offline_swing_single_writer SET updated_at=? WHERE id=1",
                    (now.isoformat(),),
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

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
                previous = datetime.fromisoformat(str(conn.execute(
                    "SELECT updated_at FROM offline_swing_single_writer WHERE id=1"
                ).fetchone()[0]))
                if previous.tzinfo is None or at.astimezone(UTC) < previous.astimezone(UTC):
                    raise OfflineRunnerRefused("finish clock regressed")
                updated = conn.execute(
                    "UPDATE offline_swing_runs SET state=?,finished_at=? "
                    "WHERE slot=? AND token=? AND state='RUNNING'",
                    (outcome, now, row[2], token),
                ).rowcount
                if updated != 1:
                    raise OfflineRunnerRefused("durable run row missing; cannot release fence")
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

    def health(self, *, now: datetime) -> OfflineFenceHealth:
        """Read-only health for local operator alerts; never touches a broker."""
        return self.fence.health(now=now)

    def inspect(self, *, now: datetime) -> dict[str, Any]:
        """Read-only local operations snapshot, not a broker health claim.

        No /pnl, order lookup, quote, credential, POST or grant-use request.
        It cannot assert that an actual broker is flat, nor release the fence.
        """
        fence = self.fence.health(now=now)
        ledger = self.controller.runtime.ledger
        state = ledger.state()
        lineage = self.controller.adapter._port._lineage
        if lineage is None:
            raise OfflineRunnerRefused("durable SideDeck order lineage is unavailable")
        orders = lineage.orders()
        owned = lineage.owned_positions()
        unknown = sum(1 for order in orders if order["state"] == "OUTCOME_UNKNOWN")
        pending = sum(1 for order in orders if order["state"] == "PENDING_SUBMIT")
        close_pending = sum(1 for order in orders
                            if order["kind"] == "CLOSE" and order["state"] == "ACCEPTED")
        alerts = list(fence.alerts)
        if state.killed:
            alerts.append("POLICY_KILL_SWITCH_ENGAGED")
        if unknown or pending or close_pending:
            alerts.append("ORDER_LINEAGE_RECONCILIATION_REQUIRED")
        if len(lineage.baseline_position_ids) != 4:
            alerts.append("PROTECTED_BASELINE_COUNT_MISMATCH")
        return {
            "schema": "sidedeck.sd152.offline-ops-status/1",
            "fence": fence.report(),
            "policy_kill_switch": bool(state.killed),
            "policy_open_positions": len(ledger.open_positions()),
            "durable_owned_open_positions": sum(1 for pos in owned
                                                if pos["state"] == "OPEN"),
            "durable_unknown_order_count": unknown,
            "durable_pending_submit_count": pending,
            "durable_accepted_close_count": close_pending,
            "protected_original_positions": len(lineage.baseline_position_ids),
            "alerts": alerts,
            "broker_route": "SIMULATED_LOCAL",
            "broker_account_verified": False,
            "execution_release": "ETORO_DEMO_NOT_RELEASED",
        }

    def recovery_dossier(self, *, now: datetime) -> dict[str, Any]:
        """Classify local uncertain orders for a separately authorised GET-only review.

        This method NEVER executes recovery, calls the fake broker, clears a HALT,
        uses a grant or permits a new POST. It is an operator checklist, not a
        licence to call /pnl. An unknown close without a durable orderId cannot
        be looked up via close-info: it requires a separately signed whole-account
        reconciliation and protection of the original baseline first.
        """
        if now.tzinfo is None or now.utcoffset() is None:
            raise OfflineRunnerRefused("recovery dossier requires timezone-aware time")
        fence = self.fence.health(now=now)
        ledger = self.controller.runtime.ledger
        state = ledger.state()
        lineage = self.controller.adapter._port._lineage
        if lineage is None:
            raise OfflineRunnerRefused("recovery dossier requires durable order lineage")
        orders = lineage.orders()
        owned = {int(pos["position_id"]): pos for pos in lineage.owned_positions()}
        items: list[dict[str, Any]] = []
        for row in orders:
            kind, status = str(row["kind"]), str(row["state"])
            ref = str(row["reference_id"])
            order_id = row["order_id"]
            position_id = row["position_id"]
            action: str | None = None
            if kind == "OPEN":
                if status in {"PENDING_SUBMIT", "OUTCOME_UNKNOWN"}:
                    action = "ORDER_REFERENCE_LOOKUP_GET_ONLY"
                elif status == "ACCEPTED" and not any(
                    int(pos["order_id"]) == int(order_id)
                    for pos in owned.values() if order_id is not None
                ):
                    action = "VERIFY_ACCEPTED_OPEN_GET_ONLY"
            elif kind == "CLOSE":
                if status in {"PENDING_SUBMIT", "OUTCOME_UNKNOWN"}:
                    # No trusted close orderId: never invent one or repeat POST.
                    action = "SIGNED_WHOLE_ACCOUNT_RECONCILIATION_ONLY"
                elif status == "ACCEPTED":
                    if order_id is None:
                        action = "SIGNED_WHOLE_ACCOUNT_RECONCILIATION_ONLY"
                    else:
                        action = "SIGNED_CLOSE_INFO_THEN_ACCOUNT_GET_ONLY"
                elif status == "FILLED" and (
                    position_id is None or int(position_id) not in owned
                    or owned[int(position_id)]["state"] != "CLOSED"
                ):
                    action = "DURABLE_LEDGER_DISCREPANCY_MANUAL_REVIEW"
            else:
                raise OfflineRunnerRefused("unknown durable broker order kind")
            if action is not None:
                items.append({
                    "reference_id": ref,
                    "kind": kind,
                    "durable_state": status,
                    "accepted_order_id": None if order_id is None else int(order_id),
                    "owned_position_id": None if position_id is None else int(position_id),
                    "review_action": action,
                    "signed_read_and_audit_required": True,
                    "automatic_post_allowed": False,
                })
        if state.killed:
            status = "HALTED_REVIEW_REQUIRED"
        elif fence.state != "IDLE" or items:
            status = "RECONCILIATION_REQUIRED"
        else:
            status = "NO_LOCAL_UNCERTAIN_ORDERS"
        return {
            "schema": "sidedeck.sd152.offline-recovery-dossier/1",
            "status": status,
            "fence": fence.report(),
            "policy_kill_switch": bool(state.killed),
            "protected_original_positions": len(lineage.baseline_position_ids),
            "uncertain_orders": items,
            "automatic_get_allowed": False,
            "automatic_post_allowed": False,
            "clear_halt_allowed": False,
            "broker_account_verified": False,
            "broker_route": "SIMULATED_LOCAL",
            "execution_release": "ETORO_DEMO_NOT_RELEASED",
        }

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
            self.fence.heartbeat(token, owner=owner, at=self.clock())
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
