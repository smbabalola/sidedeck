"""Strictly read-only SD-152 worker fence observation; not a recovery decision.

Read only a specifically configured local file. Never open/create a missing
database, mutate a worker fence, or infer broker/account health from it.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def readonly_fence_status(path: str | None, *, now: datetime) -> dict[str, Any]:
    incidents = ["RECOVERY_EVIDENCE_UNAVAILABLE"]
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("timezone-aware clock required")
    state = "UNVERIFIED"
    age: int | None = None
    if path is None:
        incidents.append("OFFLINE_FENCE_NOT_CONFIGURED")
    else:
        try:
            target = Path(path)
            if target.is_symlink() or not target.is_file():
                raise ValueError("fence file absent or symbolic link")
            with closing(sqlite3.connect(target.resolve(strict=True).as_uri() + "?mode=ro",
                                         uri=True, timeout=2)) as db:
                db.execute("PRAGMA query_only=ON")
                row = db.execute(
                    "SELECT state,token,slot,updated_at FROM offline_swing_single_writer WHERE id=1"
                ).fetchone()
                if row is None or row[0] not in ("IDLE", "RUNNING", "UNRESOLVED"):
                    raise ValueError("missing or invalid fence")
                state, token, slot, stamp = row
                if (state == "IDLE" and token
                        or state in ("RUNNING", "UNRESOLVED") and not slot
                        or state == "RUNNING" and not token):
                    raise ValueError("inconsistent fence")
                if state == "RUNNING":
                    worker = db.execute(
                        "SELECT 1 FROM offline_swing_runs WHERE slot=? AND token=? AND state='RUNNING'",
                        (slot, token),
                    ).fetchone()
                    if worker is None:
                        raise ValueError("worker row mismatch")
                if state != "IDLE":
                    dt = datetime.fromisoformat(str(stamp))
                    if dt.tzinfo is None or dt.utcoffset() is None:
                        raise ValueError("unverified heartbeat clock")
                    seconds = (now.astimezone(UTC) - dt.astimezone(UTC)).total_seconds()
                    if seconds < 0:
                        raise ValueError("heartbeat is future dated")
                    age = int(seconds)
                if state == "UNRESOLVED":
                    incidents.append("FENCE_UNRESOLVED")
                elif state == "RUNNING":
                    incidents.append("WORKER_ACTIVE_REQUIRES_OBSERVATION")
                    if age is not None and age > 120:
                        incidents.append("STALE_RUNNING_HEARTBEAT_RECONCILIATION_REQUIRED")
        except (OSError, sqlite3.Error, ValueError, TypeError, OverflowError):
            state = "UNVERIFIED"
            age = None
            incidents.append("OFFLINE_FENCE_EVIDENCE_INVALID")
    return {
        "schema": "sidedeck.sd152.operator-status/1",
        "source": "LOCAL_OFFLINE_DIAGNOSTICS_ONLY",
        "status": "ACTION_REQUIRED",
        "incidents": sorted(set(incidents)),
        "fence_state": state,
        "heartbeat_age_seconds": age,
        "incident_digest_sha256": None,
        "delivery_status": "NOT_CONFIGURED",
        "recovery": "SEPARATELY_AUTHORISED_MANUAL_REVIEW_ONLY",
        "broker_account_verified": False,
        "safe_to_trade": False,
        "automatic_get_allowed": False,
        "automatic_post_allowed": False,
        "clear_halt_allowed": False,
        "execution_release": "ETORO_DEMO_NOT_RELEASED",
    }
