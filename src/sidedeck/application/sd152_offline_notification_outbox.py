"""Offline notification outbox: persistent intent only, never external delivery."""
from __future__ import annotations

import re
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class OfflineNotificationOutbox:
    """Durable queue of operator-review needs; no transport, sender or dispatch method."""

    def __init__(self, path: Path) -> None:
        self.path = path
        with closing(sqlite3.connect(path)) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS offline_notification_outbox (
                digest TEXT PRIMARY KEY,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                observations INTEGER NOT NULL,
                delivery_state TEXT NOT NULL CHECK(delivery_state='NOT_CONFIGURED')
            )""")
            db.commit()

    def record(self, digest_report: Mapping[str, Any], *, at: datetime) -> dict[str, Any]:
        digest = digest_report.get("dedup_sha256")
        if (digest_report.get("schema") != "sidedeck.sd152.offline-alert-digest/1"
                or digest_report.get("severity") != "ACTION_REQUIRED"
                or digest_report.get("delivery_status") != "NOT_CONFIGURED"
                or digest_report.get("execution_release") != "ETORO_DEMO_NOT_RELEASED"
                or digest_report.get("safe_to_trade") is not False
                or digest_report.get("clear_halt_allowed") is not False
                or not isinstance(digest, str) or _DIGEST.fullmatch(digest) is None
                or not isinstance(at, datetime) or at.tzinfo is None
                or at.utcoffset() is None):
            raise ValueError("invalid offline escalation request")
        now = at.astimezone(UTC).isoformat()
        with closing(sqlite3.connect(self.path, isolation_level=None, timeout=30)) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                current = db.execute(
                    "SELECT last_seen, observations FROM offline_notification_outbox WHERE digest=?",
                    (digest,),
                ).fetchone()
                if current is not None and now < current[0]:
                    raise ValueError("notification outbox clock regression")
                if current is None:
                    db.execute(
                        "INSERT INTO offline_notification_outbox VALUES (?,?,?,?,?)",
                        (digest, now, now, 1, "NOT_CONFIGURED"),
                    )
                    observations = 1
                else:
                    observations = int(current[1]) + 1
                    db.execute(
                        "UPDATE offline_notification_outbox SET last_seen=?, observations=? "
                        "WHERE digest=?",
                        (now, observations, digest),
                    )
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise
        return {
            "schema": "sidedeck.sd152.offline-notification-outbox/1",
            "digest": digest,
            "observations": observations,
            "first_observation": current is None,
            "delivery_status": "NOT_CONFIGURED",
            "external_notification_confirmed": False,
            "dispatch_allowed": False,
            "incident_resolved": False,
            "safe_to_trade": False,
            "clear_halt_allowed": False,
            "execution_release": "ETORO_DEMO_NOT_RELEASED",
        }
