"""SD-145 append-only audit journal with external compare-and-append checkpoints.

The journal is deliberately not wired to broker code. Callers must append and
receive external-anchor acknowledgement before a consequential operation. A
remote outage rolls back the local append and fails closed. The existing SD-074
ExternalAnchor/Checkpoint/WriteOnceDirectoryAnchor contract is reused.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sidedeck.application.sd063_autonomous_demo_policy import GENESIS
from sidedeck.application.sd074_external_anchor import Checkpoint, ExternalAnchor, ledger_id_for

_HEX = re.compile(r"[0-9a-f]{64}")
_EVENTS = frozenset({"POLICY", "GRANT", "GRANT_USE", "ORDER_RESERVATION", "SEND",
                     "RECONCILIATION", "REVOCATION"})


class AuditJournalError(ValueError):
    """Audit evidence could not be verified or durably anchored."""


@dataclass(frozen=True)
class AuditRecord:
    stream_id: str
    sequence: int
    event_type: str
    entity_id: str
    at: str
    payload: dict[str, Any]
    previous_hash: str
    record_hash: str


class AuditJournal:
    """SQLite event chain whose every append is externally checkpointed before return."""

    def __init__(self, path: str | Path, *, stream_id: str, anchor: ExternalAnchor,
                 device_key: bytes) -> None:
        if not stream_id or len(stream_id) > 160:
            raise AuditJournalError("invalid audit stream identity")
        if not isinstance(device_key, bytes) or len(device_key) < 32:
            raise AuditJournalError("audit device key must contain at least 32 bytes")
        self.stream_id, self._anchor, self._key = stream_id, anchor, device_key
        self._digest = hashlib.sha256(("sidedeck-audit:" + stream_id).encode()).hexdigest()
        self._ledger_id = ledger_id_for(self._digest)
        self._db = sqlite3.connect(Path(path), timeout=30, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.execute("""CREATE TABLE IF NOT EXISTS audit_records (
            sequence INTEGER PRIMARY KEY, event_type TEXT NOT NULL, entity_id TEXT NOT NULL,
            at TEXT NOT NULL, payload TEXT NOT NULL, previous_hash TEXT NOT NULL,
            record_hash TEXT NOT NULL UNIQUE)""")

    def close(self) -> None:
        self._db.close()

    def _mac(self, cp: Checkpoint) -> str:
        return hmac.new(self._key, cp.body(), hashlib.sha256).hexdigest()

    def _remote_history(self) -> list[Checkpoint]:
        try:
            history = sorted(self._anchor.history(self._ledger_id), key=lambda c: c.count)
        except Exception as exc:
            raise AuditJournalError("audit anchor unavailable; operation refused") from exc
        previous_count, previous_head = -1, ""
        for cp in history:
            if cp.ledger_id != self._ledger_id or cp.policy_digest != self._digest \
                    or type(cp.count) is not int or cp.count != previous_count + 1 \
                    or not _HEX.fullmatch(cp.head) or not hmac.compare_digest(cp.mac, self._mac(cp)) \
                    or (cp.prev_count, cp.prev_head) != (previous_count, previous_head):
                raise AuditJournalError("audit anchor chain failed authentication")
            previous_count, previous_head = cp.count, cp.head
        if history and (history[0].count, history[0].head) != (0, GENESIS):
            raise AuditJournalError("audit anchor genesis is missing")
        return history

    def _local_head(self) -> tuple[int, str]:
        previous = GENESIS
        expected_sequence = 1
        rows = self._db.execute("SELECT * FROM audit_records ORDER BY sequence").fetchall()
        for row in rows:
            if row["sequence"] != expected_sequence or row["previous_hash"] != previous:
                raise AuditJournalError("local audit chain sequence or predecessor is broken")
            body = {"stream_id": self.stream_id, "sequence": expected_sequence,
                    "event_type": row["event_type"], "entity_id": row["entity_id"],
                    "at": row["at"], "payload": json.loads(row["payload"]),
                    "previous_hash": previous}
            digest = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                                ensure_ascii=False).encode()).hexdigest()
            if digest != row["record_hash"]:
                raise AuditJournalError("local audit record was modified")
            previous, expected_sequence = digest, expected_sequence + 1
        return expected_sequence - 1, previous

    def initialize(self, at: datetime) -> Checkpoint:
        """Explicitly publish genesis; construction/startup performs no anchor I/O."""
        if at.tzinfo is None or at.utcoffset() is None:
            raise AuditJournalError("anchor time must be timezone-aware")
        self._db.execute("BEGIN IMMEDIATE")
        try:
            if self._local_head() != (0, GENESIS) or self._remote_history():
                raise AuditJournalError("audit genesis already exists or local journal is not empty")
            checkpoint = self._checkpoint(0, GENESIS, -1, "", at)
            self._anchor.append(checkpoint)
            self._db.commit()
            return checkpoint
        except Exception:
            self._db.rollback()
            raise

    def append(self, event_type: str, *, entity_id: str, payload: dict[str, Any],
               at: datetime) -> AuditRecord:
        """Commit locally and externally as one fail-closed operation."""
        if event_type not in _EVENTS or not entity_id or len(entity_id) > 200:
            raise AuditJournalError("unsupported audit event or entity identity")
        if at.tzinfo is None or at.utcoffset() is None:
            raise AuditJournalError("audit timestamp must be timezone-aware")
        try:
            canonical_payload = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                           ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError):
            raise AuditJournalError("audit payload must be canonical JSON") from None
        moment = at.astimezone(timezone.utc).isoformat()
        self._db.execute("BEGIN IMMEDIATE")
        try:
            history = self._remote_history()
            count, head = self._local_head()
            if not history or (history[-1].count, history[-1].head) != (count, head):
                raise AuditJournalError("local and external audit heads differ")
            sequence = count + 1
            body = {"stream_id": self.stream_id, "sequence": sequence,
                    "event_type": event_type, "entity_id": entity_id, "at": moment,
                    "payload": json.loads(canonical_payload), "previous_hash": head}
            record_hash = hashlib.sha256(json.dumps(body, sort_keys=True,
                separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
            self._db.execute("INSERT INTO audit_records VALUES(?,?,?,?,?,?,?)",
                             (sequence, event_type, entity_id, moment, canonical_payload,
                              head, record_hash))
            checkpoint = self._checkpoint(sequence, record_hash,
                                          history[-1].count, history[-1].head, at)
            self._anchor.append(checkpoint)
            self._db.commit()
            return AuditRecord(self.stream_id, sequence, event_type, entity_id, moment,
                               json.loads(canonical_payload), head, record_hash)
        except Exception:
            self._db.rollback()
            raise

    def verify(self) -> tuple[int, str]:
        """Verify local rows against the authenticated external checkpoint head."""
        self._db.execute("BEGIN IMMEDIATE")
        try:
            history = self._remote_history()
            local = self._local_head()
            if not history or (history[-1].count, history[-1].head) != local:
                raise AuditJournalError("audit journal is missing, rolled back or unpublished")
            self._db.commit()
            return local
        except Exception:
            self._db.rollback()
            raise

    def records(self) -> tuple[AuditRecord, ...]:
        count, _ = self.verify()
        del count
        rows = self._db.execute("SELECT * FROM audit_records ORDER BY sequence").fetchall()
        return tuple(AuditRecord(self.stream_id, row["sequence"], row["event_type"],
                                 row["entity_id"], row["at"], json.loads(row["payload"]),
                                 row["previous_hash"], row["record_hash"]) for row in rows)

    def _checkpoint(self, count: int, head: str, previous_count: int, previous_head: str,
                    at: datetime) -> Checkpoint:
        unsigned = Checkpoint(self._ledger_id, self._digest, count, head, previous_count,
                              previous_head, at.astimezone(timezone.utc).isoformat(), "")
        return Checkpoint(**{**asdict(unsigned), "mac": self._mac(unsigned)})
