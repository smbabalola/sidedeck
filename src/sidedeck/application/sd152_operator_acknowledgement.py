"""Durable local operator acknowledgement; neither delivery nor broker recovery."""
from __future__ import annotations

import re
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_ACTOR = re.compile(r"[a-zA-Z0-9_.@-]{1,96}\Z")


class OfflineOperatorAcknowledgements:
    """Operator-only SQLite record. Acknowledgement never suppresses escalation."""

    def __init__(self, path: Path) -> None:
        self.path = path
        with closing(sqlite3.connect(path)) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS offline_operator_ack (
                digest TEXT PRIMARY KEY, actor TEXT NOT NULL, acknowledged_at TEXT NOT NULL
            )""")
            db.commit()

    def acknowledge(self, digest_report: Mapping[str, Any], *,
                    actor: str, at: datetime) -> dict[str, Any]:
        digest = digest_report.get("dedup_sha256")
        if (digest_report.get("schema") != "sidedeck.sd152.offline-alert-digest/1"
                or digest_report.get("severity") != "ACTION_REQUIRED"
                or digest_report.get("delivery_status") != "NOT_CONFIGURED"
                or digest_report.get("execution_release") != "ETORO_DEMO_NOT_RELEASED"
                or digest_report.get("safe_to_trade") is not False
                or digest_report.get("clear_halt_allowed") is not False
                or not isinstance(digest, str) or _DIGEST.fullmatch(digest) is None
                or not isinstance(actor, str) or _ACTOR.fullmatch(actor) is None
                or not isinstance(at, datetime) or at.tzinfo is None
                or at.utcoffset() is None):
            raise ValueError("invalid non-executable operator acknowledgement")
        when = at.astimezone(UTC).isoformat()
        with closing(sqlite3.connect(self.path, isolation_level=None, timeout=30)) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                existing = db.execute(
                    "SELECT actor, acknowledged_at FROM offline_operator_ack WHERE digest=?",
                    (digest,),
                ).fetchone()
                if existing is None:
                    db.execute("INSERT INTO offline_operator_ack VALUES (?,?,?)",
                               (digest, actor, when))
                elif existing != (actor, when):
                    raise ValueError("acknowledgement already recorded; immutable")
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise
        return {
            "schema": "sidedeck.sd152.offline-operator-ack/1",
            "digest": digest, "actor": actor,
            "acknowledged_at": when, "already_recorded": existing is not None,
            "delivery_status": "NOT_CONFIGURED",
            "external_notification_confirmed": False,
            "incident_resolved": False, "safe_to_trade": False,
            "clear_halt_allowed": False,
            "execution_release": "ETORO_DEMO_NOT_RELEASED",
        }
