"""Durable offline replay fence for incident acknowledgement authorization.

Not identity verification: only a separately trusted verifier can establish
a principal. This fence enforces one local nonce per authorization attempt.
"""
from __future__ import annotations

import re
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

_NONCE = re.compile(r"[A-Za-z0-9_-]{16,128}\Z")


class OfflineAcknowledgementReplayFence:
    def __init__(self, path: Path) -> None:
        self.path = path
        with closing(sqlite3.connect(path)) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS offline_ack_nonces (
                nonce TEXT PRIMARY KEY, incident_digest TEXT NOT NULL,
                subject TEXT NOT NULL, accepted_at TEXT NOT NULL
            )""")
            db.commit()

    def reserve(self, authorization: Mapping[str, Any], *,
                nonce: str, at: datetime) -> dict[str, Any]:
        if (authorization.get("schema") != "sidedeck.sd152.operator-incident-authorization/1"
                or authorization.get("authorization_status") != "OFFLINE_VERIFIER_ACCEPTED"
                or authorization.get("external_identity_verified") is not False
                or authorization.get("execution_release") != "ETORO_DEMO_NOT_RELEASED"
                or authorization.get("safe_to_trade") is not False
                or authorization.get("notification_dispatch_allowed") is not False
                or not isinstance(authorization.get("incident_digest"), str)
                or len(authorization["incident_digest"]) != 64
                or not isinstance(authorization.get("subject"), str)
                or not authorization["subject"]
                or not isinstance(nonce, str) or _NONCE.fullmatch(nonce) is None
                or not isinstance(at, datetime) or at.tzinfo is None
                or at.utcoffset() is None):
            raise ValueError("invalid offline acknowledgement authorization")
        with closing(sqlite3.connect(self.path, isolation_level=None, timeout=30)) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute("INSERT INTO offline_ack_nonces VALUES (?,?,?,?)",
                           (nonce, authorization["incident_digest"],
                            authorization["subject"], at.astimezone(UTC).isoformat()))
                db.execute("COMMIT")
            except sqlite3.IntegrityError as exc:
                db.execute("ROLLBACK")
                raise ValueError("replayed operator acknowledgement nonce") from exc
            except Exception:
                db.execute("ROLLBACK")
                raise
        return {
            "schema": "sidedeck.sd152.offline-ack-replay/1",
            "nonce_reserved": True,
            "external_identity_verified": False,
            "safe_to_trade": False,
            "clear_halt_allowed": False,
            "execution_release": "ETORO_DEMO_NOT_RELEASED",
        }
