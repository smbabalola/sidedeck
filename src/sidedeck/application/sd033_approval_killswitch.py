"""Verifier-only approval and durable emergency-stop boundary."""
from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


class ApprovalError(ValueError):
    pass


SignatureVerifier = Callable[[str, str, str], bool]


def intent_digest(intent_id: str, scope: str) -> str:
    return hashlib.sha256(f"{intent_id}\n{scope}".encode("utf-8")).hexdigest()


class ApprovalKillSwitch:
    """Stores approval metadata and halt state; never creates signing secrets."""

    def __init__(self, path: str, verify_signature: SignatureVerifier) -> None:
        self._db = sqlite3.connect(Path(path), isolation_level=None)
        self._verify = verify_signature
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS paper_approvals (
              approval_id TEXT PRIMARY KEY, intent_digest TEXT NOT NULL UNIQUE,
              requester TEXT NOT NULL, approver TEXT NOT NULL, public_key TEXT NOT NULL,
              signature TEXT NOT NULL, expires_at TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS paper_kill_switch (
              singleton INTEGER PRIMARY KEY CHECK(singleton=1), halted INTEGER NOT NULL,
              changed_by TEXT NOT NULL, reason TEXT NOT NULL, changed_at TEXT NOT NULL
            );
            INSERT OR IGNORE INTO paper_kill_switch VALUES (1, 0, 'bootstrap', 'not halted', '1970-01-01T00:00:00+00:00');
            """
        )

    def approve(self, approval_id: str, intent_id: str, scope: str, requester: str,
                approver: str, public_key: str, signature: str, expires_at: datetime) -> str:
        if self.is_halted():
            raise ApprovalError("kill-switch is active")
        if not all(value.strip() for value in (approval_id, intent_id, scope, requester, approver, public_key, signature)):
            raise ApprovalError("complete approval fields are required")
        if requester.strip().casefold() == approver.strip().casefold():
            raise ApprovalError("requester and approver must be distinct")
        expiry = expires_at.astimezone(timezone.utc)
        if expiry <= datetime.now(timezone.utc):
            raise ApprovalError("approval is expired")
        digest = intent_digest(intent_id, scope)
        if not self._verify(public_key, digest, signature):
            raise ApprovalError("signature verification failed")
        try:
            self._db.execute(
                "INSERT INTO paper_approvals VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (approval_id, digest, requester, approver, public_key, signature,
                 expiry.isoformat(), datetime.now(timezone.utc).isoformat()),
            )
        except sqlite3.IntegrityError as exc:
            raise ApprovalError("approval replay or intent already approved") from exc
        return digest

    def is_halted(self) -> bool:
        return bool(self._db.execute("SELECT halted FROM paper_kill_switch WHERE singleton=1").fetchone()[0])

    def trip(self, operator: str, reason: str) -> None:
        if not operator.strip() or not reason.strip():
            raise ApprovalError("operator and reason are required")
        self._db.execute("UPDATE paper_kill_switch SET halted=1, changed_by=?, reason=?, changed_at=? WHERE singleton=1",
                         (operator, reason, datetime.now(timezone.utc).isoformat()))

    def clear(self, operator: str, confirmation: str) -> None:
        row = self._db.execute("SELECT changed_by FROM paper_kill_switch WHERE singleton=1").fetchone()
        if not operator.strip() or not confirmation.strip() or row is None:
            raise ApprovalError("separate operator clearance is required")
        if operator.strip().casefold() == row[0].strip().casefold():
            raise ApprovalError("kill-switch clearance must be a separate operator")
        self._db.execute("UPDATE paper_kill_switch SET halted=0, changed_by=?, reason=?, changed_at=? WHERE singleton=1",
                         (operator, f"CLEAR:{confirmation}", datetime.now(timezone.utc).isoformat()))

    def close(self) -> None:
        self._db.close()
