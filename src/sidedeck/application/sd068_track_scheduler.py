"""SD-068 calendar-aware DAY / SWING / POSITION job scheduler (no daemon, no network).

Each job names its exchange calendar (SD-089): ``XNYS`` sessions are computed in
``America/New_York`` and ``XLON`` sessions in ``Europe/London``, then converted to
UTC, so daylight-saving transitions and clock differences never shift a session
and the two markets never share hours by assumption. Dates outside a calendar's
covered years fail closed. Jobs on non-US calendars must be namespaced by
calendar (e.g. ``xlon.swing_review``) so US and UK slots can never collide, and
every exchange has its own per-track controls (SD-091).

The scheduler only *plans and records* runs. Persistence prevents overlapping
runs and duplicated slots, and coalesces missed slots after a restart so an
outage never triggers a burst of catch-up work. Every track is research- or
simulation-only; execution modes cannot be configured here.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from sidedeck.application.sd089_exchange_calendar import CALENDARS, US_EARLY_CLOSES
from sidedeck.application.sd089_exchange_calendar import calendar as exchange_calendar
from sidedeck.application.us_equity_calendar import COMPLETE_CALENDAR_YEARS

NEW_YORK = ZoneInfo("America/New_York")
REGULAR_OPEN = time(9, 30)
REGULAR_CLOSE = time(16, 0)
EARLY_CLOSE = time(13, 0)
# NYSE/Nasdaq 1:00 p.m. ET early closes (published exchange holiday schedules).
# Kept for compatibility; the XNYS calendar in SD-089 is the single source for sessions.
US_EQUITY_EARLY_CLOSES: frozenset[date] = frozenset(US_EARLY_CLOSES) | {date(2021, 11, 26)}
COVERED_YEARS = COMPLETE_CALENDAR_YEARS
TRACKS = ("DAY", "SWING", "POSITION", "SYSTEM")
MODES = ("RESEARCH_ONLY", "SIMULATION_ONLY")
Anchor = Literal["OPEN", "CLOSE"]


class SchedulerError(ValueError):
    pass


@dataclass(frozen=True)
class Session:
    day: date
    open_utc: datetime
    close_utc: datetime
    early_close: bool


def session_for(day: date, calendar_id: str = "XNYS") -> Session | None:
    cal = exchange_calendar(calendar_id)
    if day.year not in cal.covered_years:
        raise SchedulerError(
            f"{calendar_id} calendar does not cover {day.year}; refusing to guess sessions"
        )
    session = cal.session(day)
    if session is None:
        return None
    return Session(day, session.open_utc, session.close_utc, session.early_close)


@dataclass(frozen=True)
class Cadence:
    """``offsets`` are (anchor, minutes) pairs; ``every_minutes`` repeats inside the session.

    ``weekly_last_session`` restricts the job to the last session of each ISO week.
    """

    offsets: tuple[tuple[str, int], ...] = ()
    every_minutes: int | None = None
    interval_start_offset: int = 0   # minutes after open
    interval_end_offset: int = 0     # minutes relative to close (negative = before)
    weekly_last_session: bool = False

    def __post_init__(self) -> None:
        if not self.offsets and self.every_minutes is None:
            raise SchedulerError("a cadence needs offsets or an interval")
        if self.every_minutes is not None and not 1 <= self.every_minutes <= 240:
            raise SchedulerError("interval must be between 1 and 240 minutes")
        if any(anchor not in ("OPEN", "CLOSE") for anchor, _ in self.offsets):
            raise SchedulerError("anchor must be OPEN or CLOSE")


@dataclass(frozen=True)
class JobSpec:
    job_id: str
    track: str
    description: str
    cadence: Cadence
    lease_seconds: int = 900
    enabled: bool = True
    requires_authorization: bool = False  # e.g. authenticated broker reads
    max_lateness_seconds: int | None = None  # default: one interval, or 60 min for offsets
    calendar_id: str = "XNYS"

    def __post_init__(self) -> None:
        if self.track not in TRACKS:
            raise SchedulerError(f"unknown track {self.track}")
        if self.calendar_id not in CALENDARS:
            raise SchedulerError(f"unknown exchange calendar {self.calendar_id}")
        if self.calendar_id != "XNYS" and not self.job_id.startswith(
            f"{self.calendar_id.lower()}."
        ):
            raise SchedulerError("non-US jobs must be namespaced by calendar, e.g. 'xlon.'")
        if not self.job_id.strip() or self.lease_seconds <= 0:
            raise SchedulerError("invalid job spec")
        if self.max_lateness_seconds is not None and self.max_lateness_seconds <= 0:
            raise SchedulerError("max lateness must be positive")

    @property
    def lateness(self) -> timedelta:
        if self.max_lateness_seconds is not None:
            return timedelta(seconds=self.max_lateness_seconds)
        if self.cadence.every_minutes is not None:
            return timedelta(minutes=self.cadence.every_minutes)
        return timedelta(minutes=60)


DEFAULT_JOBS: tuple[JobSpec, ...] = (
    JobSpec("universe_refresh", "SYSTEM", "Point-in-time universe refresh (approved sources)",
            Cadence(offsets=(("OPEN", -150),))),
    JobSpec("broad_scan", "SYSTEM", "Daily broad US scan on the prior close",
            Cadence(offsets=(("OPEN", -120),)), lease_seconds=3600),
    JobSpec("day_candidate_scan", "DAY", "DAY watchlist scan during regular hours",
            Cadence(every_minutes=5, interval_start_offset=5, interval_end_offset=-15),
            lease_seconds=240),
    JobSpec("swing_review", "SWING", "SWING review: premarket, mid-session, near close",
            Cadence(offsets=(("OPEN", -30), ("OPEN", 180), ("CLOSE", -30)))),
    JobSpec("position_daily", "POSITION", "POSITION daily price/portfolio update",
            Cadence(offsets=(("CLOSE", 60),))),
    JobSpec("position_weekly", "POSITION", "POSITION weekly fundamental reassessment",
            Cadence(offsets=(("CLOSE", 120),), weekly_last_session=True), lease_seconds=7200),
    JobSpec("risk_monitor", "SYSTEM", "Portfolio risk monitoring during market hours",
            Cadence(every_minutes=1), lease_seconds=55),
    JobSpec("broker_reconcile", "SYSTEM", "Broker reconciliation (needs approved read budget)",
            Cadence(offsets=(("OPEN", -20), ("CLOSE", 20))), enabled=False,
            requires_authorization=True),
    JobSpec("performance_analysis", "SYSTEM", "After-close performance analysis",
            Cadence(offsets=(("CLOSE", 90),))),
)

# London Stock Exchange jobs (SD-091). Research/simulation planning only. DAY is
# disabled: no approved UK intraday or spread data exists (SD-094).
UK_DEFAULT_JOBS: tuple[JobSpec, ...] = (
    JobSpec("xlon.universe_refresh", "SYSTEM", "UK point-in-time universe refresh",
            Cadence(offsets=(("OPEN", -150),)), calendar_id="XLON"),
    JobSpec("xlon.broad_scan", "SYSTEM", "Daily broad UK scan on the prior LSE close",
            Cadence(offsets=(("OPEN", -120),)), lease_seconds=3600, calendar_id="XLON"),
    JobSpec("xlon.day_candidate_scan", "DAY", "UK DAY scan (blocked: no approved intraday data)",
            Cadence(every_minutes=5, interval_start_offset=5, interval_end_offset=-15),
            lease_seconds=240, enabled=False, calendar_id="XLON"),
    JobSpec("xlon.swing_review", "SWING", "UK SWING review: pre-open, mid-session, near close",
            Cadence(offsets=(("OPEN", -30), ("OPEN", 240), ("CLOSE", -30))),
            calendar_id="XLON"),
    JobSpec("xlon.position_daily", "POSITION", "UK POSITION daily update after the LSE close",
            Cadence(offsets=(("CLOSE", 60),)), calendar_id="XLON"),
    JobSpec("xlon.position_weekly", "POSITION", "UK POSITION weekly reassessment",
            Cadence(offsets=(("CLOSE", 120),), weekly_last_session=True), lease_seconds=7200,
            calendar_id="XLON"),
    JobSpec("xlon.broker_reconcile", "SYSTEM", "UK broker reconciliation (not authorized)",
            Cadence(offsets=(("OPEN", -20), ("CLOSE", 20))), enabled=False,
            requires_authorization=True, calendar_id="XLON"),
)
MULTI_EXCHANGE_JOBS: tuple[JobSpec, ...] = DEFAULT_JOBS + UK_DEFAULT_JOBS


def _is_last_session_of_week(day: date, calendar_id: str = "XNYS") -> bool:
    cal = exchange_calendar(calendar_id)
    nxt = day + timedelta(days=1)
    while nxt.isocalendar()[1] == day.isocalendar()[1]:
        if nxt.year not in cal.covered_years:
            return True
        if cal.is_session(nxt):
            return False
        nxt += timedelta(days=1)
    return True


def slots_for(job: JobSpec, day: date) -> tuple[datetime, ...]:
    session = session_for(day, job.calendar_id)
    if session is None:
        return ()
    cad = job.cadence
    if cad.weekly_last_session and not _is_last_session_of_week(day, job.calendar_id):
        return ()
    slots: set[datetime] = set()
    for anchor, minutes in cad.offsets:
        base = session.open_utc if anchor == "OPEN" else session.close_utc
        slots.add(base + timedelta(minutes=minutes))
    if cad.every_minutes is not None:
        current = session.open_utc + timedelta(minutes=cad.interval_start_offset)
        end = session.close_utc + timedelta(minutes=cad.interval_end_offset)
        while current <= end:
            slots.add(current)
            current += timedelta(minutes=cad.every_minutes)
    return tuple(sorted(slots))


@dataclass(frozen=True)
class DueRun:
    job_id: str
    track: str
    slot: datetime
    skipped_missed: int


@dataclass(frozen=True)
class ClaimResult:
    claimed: bool
    reason: str


class SchedulerStore:
    """Persistent run ledger and per-track controls in a caller-owned SQLite file."""

    def __init__(self, path: Path, jobs: tuple[JobSpec, ...] = DEFAULT_JOBS) -> None:
        if len({j.job_id for j in jobs}) != len(jobs):
            raise SchedulerError("duplicate job ids")
        self._path = path
        self.jobs = {j.job_id: j for j in jobs}
        with closing(self._conn()) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS runs (job_id TEXT, slot TEXT, status TEXT, owner TEXT,"
                " lease_until TEXT, attempts INTEGER, updated TEXT, PRIMARY KEY (job_id, slot))"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS tracks (track TEXT PRIMARY KEY, enabled INTEGER,"
                " mode TEXT)"
            )
            for track in TRACKS:
                conn.execute(
                    "INSERT OR IGNORE INTO tracks VALUES (?, 1, 'RESEARCH_ONLY')", (track,)
                )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS exchange_tracks (calendar_id TEXT, track TEXT,"
                " enabled INTEGER, mode TEXT, PRIMARY KEY (calendar_id, track))"
            )
            for cal_id in sorted({j.calendar_id for j in jobs}):
                for track in TRACKS:
                    conn.execute(
                        "INSERT OR IGNORE INTO exchange_tracks VALUES (?, ?, 1, 'RESEARCH_ONLY')",
                        (cal_id, track),
                    )

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path, isolation_level=None)

    # --- track controls -------------------------------------------------------
    def set_track(self, track: str, *, enabled: bool, mode: str = "RESEARCH_ONLY") -> None:
        if track not in TRACKS:
            raise SchedulerError(f"unknown track {track}")
        if mode not in MODES:
            raise SchedulerError(
                "only RESEARCH_ONLY or SIMULATION_ONLY can be set here; execution needs a "
                "separately owner-released autonomous Demo policy (SD-063/SD-064)"
            )
        with closing(self._conn()) as conn:
            conn.execute("UPDATE tracks SET enabled=?, mode=? WHERE track=?",
                         (int(enabled), mode, track))

    def track_controls(self) -> dict[str, tuple[bool, str]]:
        """Stored controls; an unknown mode (e.g. a hand-edited database) disables the track."""
        with closing(self._conn()) as conn:
            rows = conn.execute("SELECT track, enabled, mode FROM tracks").fetchall()
        return {
            str(t): (bool(e) and m in MODES, str(m) if m in MODES else "INVALID_MODE_DISABLED")
            for t, e, m in rows
        }

    def set_exchange_track(
        self, calendar_id: str, track: str, *, enabled: bool, mode: str = "RESEARCH_ONLY",
    ) -> None:
        """Per-exchange track control; disabling UK SWING never touches US SWING."""
        if calendar_id not in CALENDARS or track not in TRACKS:
            raise SchedulerError("unknown calendar or track")
        if mode not in MODES:
            raise SchedulerError("only RESEARCH_ONLY or SIMULATION_ONLY can be set here")
        with closing(self._conn()) as conn:
            conn.execute(
                "INSERT INTO exchange_tracks VALUES (?, ?, ?, ?) ON CONFLICT(calendar_id, track)"
                " DO UPDATE SET enabled=excluded.enabled, mode=excluded.mode",
                (calendar_id, track, int(enabled), mode),
            )

    def exchange_track_controls(self) -> dict[tuple[str, str], tuple[bool, str]]:
        """Stored per-exchange controls; an unknown mode disables that exchange track."""
        with closing(self._conn()) as conn:
            rows = conn.execute(
                "SELECT calendar_id, track, enabled, mode FROM exchange_tracks"
            ).fetchall()
        return {
            (str(c), str(t)): (bool(e) and m in MODES,
                               str(m) if m in MODES else "INVALID_MODE_DISABLED")
            for c, t, e, m in rows
        }

    def _runnable(self, job: JobSpec) -> str | None:
        if not job.enabled:
            return "JOB_DISABLED"
        if job.requires_authorization:
            return "REQUIRES_AUTHORIZATION"
        if not self.track_controls().get(job.track, (False, ""))[0]:
            return "TRACK_DISABLED"
        if not self.exchange_track_controls().get((job.calendar_id, job.track), (False, ""))[0]:
            return "EXCHANGE_TRACK_DISABLED"
        return None

    # --- planning -------------------------------------------------------------
    def due(self, now: datetime) -> tuple[DueRun, ...]:
        """Latest due slot per enabled job; older unrecorded slots become SKIPPED_MISSED."""
        if now.tzinfo is None:
            raise SchedulerError("timezone-aware time required")
        now = now.astimezone(UTC)
        due: list[DueRun] = []
        with closing(self._conn()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            for job in self.jobs.values():
                if self._runnable(job) is not None:
                    continue
                cal = exchange_calendar(job.calendar_id)
                local_day = cal.local_date(now)
                previous = local_day - timedelta(days=1)
                days = ([previous] if previous.year in cal.covered_years else []) + [local_day]
                slots = [s for d in days for s in slots_for(job, d) if s <= now]
                recorded = {
                    row[0] for row in conn.execute(
                        "SELECT slot FROM runs WHERE job_id=?", (job.job_id,)
                    )
                }
                pending = [s for s in slots if s.isoformat() not in recorded]
                if not pending:
                    continue
                # A slot later than the job's lateness window is never run (e.g. a DAY scan
                # after the close or after an outage); it is logged as missed instead.
                fresh = pending[-1] if now - pending[-1] <= job.lateness else None
                for missed in (pending if fresh is None else pending[:-1]):
                    conn.execute(
                        "INSERT INTO runs VALUES (?,?,?,?,?,?,?)",
                        (job.job_id, missed.isoformat(), "SKIPPED_MISSED", "", "", 0,
                         now.isoformat()),
                    )
                if fresh is not None:
                    due.append(DueRun(job.job_id, job.track, fresh, len(pending) - 1))
            conn.execute("COMMIT")
        return tuple(sorted(due, key=lambda r: (r.slot, r.job_id)))

    # --- execution ledger -----------------------------------------------------
    def claim(self, job_id: str, slot: datetime, owner: str, now: datetime) -> ClaimResult:
        job = self.jobs.get(job_id)
        if job is None:
            raise SchedulerError(f"unknown job {job_id}")
        if now.tzinfo is None or slot.tzinfo is None:
            raise SchedulerError("timezone-aware time required")
        now, slot = now.astimezone(UTC), slot.astimezone(UTC)
        blocked = self._runnable(job)
        if blocked is not None:
            return ClaimResult(False, blocked)
        if slot not in slots_for(job, exchange_calendar(job.calendar_id).local_date(slot)):
            return ClaimResult(False, "NOT_A_SCHEDULED_SLOT")
        if slot > now:
            return ClaimResult(False, "NOT_YET_DUE")
        if now - slot > job.lateness:
            return ClaimResult(False, "TOO_LATE")
        lease_until = (now + timedelta(seconds=job.lease_seconds)).isoformat()
        with closing(self._conn()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            running = conn.execute(
                "SELECT slot, lease_until FROM runs WHERE job_id=? AND status='RUNNING'", (job_id,)
            ).fetchall()
            live = [r for r in running if datetime.fromisoformat(r[1]) > now]
            if live:
                conn.execute("ROLLBACK")
                return ClaimResult(False, "OVERLAP_RUNNING")
            row = conn.execute(
                "SELECT status, attempts FROM runs WHERE job_id=? AND slot=?",
                (job_id, slot.isoformat()),
            ).fetchone()
            for stale_slot, _ in running:
                if stale_slot != slot.isoformat():
                    conn.execute(
                        "UPDATE runs SET status='ABANDONED_LEASE_EXPIRED', updated=? "
                        "WHERE job_id=? AND slot=?", (now.isoformat(), job_id, stale_slot),
                    )
            if row is None:
                conn.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?)",
                             (job_id, slot.isoformat(), "RUNNING", owner, lease_until, 1,
                              now.isoformat()))
                reason = "CLAIMED"
            elif row[0] == "RUNNING":  # expired lease on this very slot: take over
                conn.execute(
                    "UPDATE runs SET owner=?, lease_until=?, attempts=?, updated=? "
                    "WHERE job_id=? AND slot=?",
                    (owner, lease_until, row[1] + 1, now.isoformat(), job_id, slot.isoformat()),
                )
                reason = "LEASE_TAKEOVER"
            else:
                conn.execute("ROLLBACK")
                return ClaimResult(False, f"ALREADY_{row[0]}")
            conn.execute("COMMIT")
            return ClaimResult(True, reason)

    def finish(self, job_id: str, slot: datetime, owner: str, now: datetime, *, ok: bool) -> None:
        if now.tzinfo is None or slot.tzinfo is None:
            raise SchedulerError("timezone-aware time required")
        now, slot = now.astimezone(UTC), slot.astimezone(UTC)
        with closing(self._conn()) as conn:
            updated = conn.execute(
                "UPDATE runs SET status=?, updated=? WHERE job_id=? AND slot=? AND owner=? "
                "AND status='RUNNING'",
                ("COMPLETED" if ok else "FAILED", now.isoformat(), job_id, slot.isoformat(), owner),
            ).rowcount
        if updated != 1:
            raise SchedulerError("run is not held by this owner (lease lost or already finished)")

    def history(self, job_id: str) -> tuple[tuple[str, str, int], ...]:
        with closing(self._conn()) as conn:
            rows = conn.execute(
                "SELECT slot, status, attempts FROM runs WHERE job_id=? ORDER BY slot", (job_id,)
            ).fetchall()
        return tuple((str(s), str(st), int(a)) for s, st, a in rows)
