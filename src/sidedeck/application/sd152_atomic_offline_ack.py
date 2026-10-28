"""Atomic offline acknowledgement + replay reservation on one SQLite database.

The caller must supply an offline fixture authorization; this is NOT an
authenticated acknowledgement and never grants broker or delivery privileges.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from sidedeck.application.sd152_digest_integrity import validate_offline_digest
from sidedeck.application.sd152_ack_replay_fence import OfflineAcknowledgementReplayFence, _NONCE
from sidedeck.application.sd152_operator_acknowledgement import OfflineOperatorAcknowledgements, _ACTOR, _DIGEST


class AtomicOfflineAcknowledgement:
    def __init__(self, path: Path) -> None:
        self.path = path
        OfflineAcknowledgementReplayFence(path)
        OfflineOperatorAcknowledgements(path)

    def record(self, digest_report: Mapping[str, Any], authorization: Mapping[str, Any],
               *, nonce: str, at: datetime) -> dict[str, Any]:
        digest = digest_report.get("dedup_sha256")
        actor = authorization.get("subject")
        if (
            not validate_offline_digest(digest_report)
            or digest_report.get("schema") != "sidedeck.sd152.offline-alert-digest/1"
            or digest_report.get("severity") != "ACTION_REQUIRED"
            or digest_report.get("delivery_status") != "NOT_CONFIGURED"
            or digest_report.get("execution_release") != "ETORO_DEMO_NOT_RELEASED"
            or digest_report.get("safe_to_trade") is not False
            or digest_report.get("clear_halt_allowed") is not False
            or not isinstance(digest, str) or _DIGEST.fullmatch(digest) is None
            or authorization.get("schema") != "sidedeck.sd152.operator-incident-authorization/1"
            or authorization.get("authorization_status") != "OFFLINE_VERIFIER_ACCEPTED"
            or authorization.get("external_identity_verified") is not False
            or authorization.get("incident_digest") != digest
            or authorization.get("execution_release") != "ETORO_DEMO_NOT_RELEASED"
            or authorization.get("safe_to_trade") is not False
            or authorization.get("notification_dispatch_allowed") is not False
            or not isinstance(actor, str) or _ACTOR.fullmatch(actor) is None
            or not isinstance(nonce, str) or _NONCE.fullmatch(nonce) is None
            or not isinstance(at, datetime) or at.tzinfo is None
            or at.utcoffset() is None
        ):
            raise ValueError("offline acknowledgement evidence invalid")
        when = at.astimezone(UTC).isoformat()
        with closing(sqlite3.connect(self.path, isolation_level=None, timeout=30)) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                existing = db.execute(
                    "SELECT actor, acknowledged_at FROM offline_operator_ack WHERE digest=?",
                    (digest,),
                ).fetchone()
                if existing is not None:
                    raise ValueError("incident already acknowledged; no nonce consumed")
                db.execute("INSERT INTO offline_ack_nonces VALUES (?,?,?,?)",
                           (nonce, digest, actor, when))
                db.execute("INSERT INTO offline_operator_ack VALUES (?,?,?)",
                           (digest, actor, when))
                db.execute("COMMIT")
            except sqlite3.IntegrityError as exc:
                db.execute("ROLLBACK")
                raise ValueError("replayed nonce or duplicate acknowledgement") from exc
            except Exception:
                db.execute("ROLLBACK")
                raise
        return {
            "schema": "sidedeck.sd152.offline-operator-ack/1",
            "digest": digest, "actor": actor, "acknowledged_at": when,
            "already_recorded": False,
            "authorization_provenance": "OFFLINE_FIXTURE_ONLY",
            "external_identity_verified": False,
            "nonce_reserved": True,
            "delivery_status": "NOT_CONFIGURED",
            "external_notification_confirmed": False,
            "incident_resolved": False, "safe_to_trade": False,
            "clear_halt_allowed": False,
            "execution_release": "ETORO_DEMO_NOT_RELEASED",
        }
