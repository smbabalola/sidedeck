"""Durable local-only incident journal; not a notification sender or release gate."""
from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from sidedeck.application.sd152_digest_integrity import validate_offline_digest


class OfflineAlertJournal:
    """Atomic deduplication by alert digest; only local SQLite, never broker I/O."""

    def __init__(self, path: Path) -> None:
        self.path = path
        with closing(sqlite3.connect(path)) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS offline_alert_journal (
                digest TEXT PRIMARY KEY, first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL, observations INTEGER NOT NULL,
                severity TEXT NOT NULL)""")
            db.commit()

    def record(self, report: Mapping[str, Any], *, at: datetime) -> dict[str, Any]:
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("timezone-aware timestamp required")
        digest = report.get("dedup_sha256")
        if (report.get("schema") != "sidedeck.sd152.offline-alert-digest/1"
                or report.get("execution_release") != "ETORO_DEMO_NOT_RELEASED"
                or report.get("safe_to_trade") is not False
                or report.get("clear_halt_allowed") is not False
                or report.get("delivery_status") != "NOT_CONFIGURED"
                or report.get("severity") not in ("ACTION_REQUIRED", "INFORMATIONAL")
                or not isinstance(digest, str) or len(digest) != 64
                or any(c not in "0123456789abcdef" for c in digest)):
            raise ValueError("invalid or executable alert digest")
        if report["severity"] == "ACTION_REQUIRED" and not validate_offline_digest(report):
            raise ValueError("critical alert digest integrity invalid")
        now = at.astimezone(UTC).isoformat()
        with closing(sqlite3.connect(self.path, isolation_level=None, timeout=30)) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                old = db.execute("SELECT last_seen,observations FROM offline_alert_journal WHERE digest=?",
                                 (digest,)).fetchone()
                if old is not None and now < old[0]:
                    raise ValueError("alert clock regression")
                if old is None:
                    db.execute("INSERT INTO offline_alert_journal VALUES (?,?,?,?,?)",
                               (digest, now, now, 1, report["severity"]))
                    observations = 1
                else:
                    observations = int(old[1]) + 1
                    db.execute("UPDATE offline_alert_journal SET last_seen=?, observations=? WHERE digest=?",
                               (now, observations, digest))
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise
        return {"schema": "sidedeck.sd152.offline-alert-record/1",
                "first_observation": old is None, "observations": observations,
                "delivery_status": "NOT_CONFIGURED", "safe_to_trade": False,
                "clear_halt_allowed": False, "execution_release": "ETORO_DEMO_NOT_RELEASED"}
