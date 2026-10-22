"""SD-064 owner-signed network unlock grants (replaces editing a source constant).

A grant is a small canonical JSON document the **owner** signs with their SSH key in the
dedicated namespace ``sidedeck-network-unlock-grant``. It unlocks the eToro **Demo** order
network for exactly one subject digest (a signed pilot release or, later, a separately
released autonomous Demo policy), inside a bounded time window, with request/write caps.

Rules (all fail closed: any error means "locked"):

* **Scope:** ``broker`` must be ``etoro-demo`` (Real is refused permanently); ``kind`` is
  ``pilot_release`` (window <= 8 h) or ``autonomous_policy`` (window <= 7 days); the subject
  is one 64-hex digest; caps are positive and bounded.
* **Signature:** verified with ``ssh-keygen -Y verify`` against an ``allowed_signers`` file
  that must hold exactly the pinned owner key (SHA-256 of the key blob) for the owner
  principal. ``issued_by`` must equal that principal.
* **No self-authorization:** SideDeck holds no private key; a grant naming any other
  principal, or verified against any other key, is refused. Nothing in this module can
  create a signature.
* **Expiry:** ``not_before <= now < expires_at`` at every check, independently of any later
  re-lock commit.
* **Audit:** every activation, check refusal and revocation is appended to a hash-chained
  SQLite ledger; ``verify_chain`` detects any edit or mid-chain deletion. **Limitation:**
  truncating the newest rows leaves a valid prefix, so a hidden revocation needs an external
  anchor (not yet built); short signed windows (8 h / 7 days) bound that exposure.
  Revocation is always allowed (it only reduces privilege) and is permanent.

This module grants nothing on its own and is not yet consulted by the order transport;
wiring it in (replacing ``UNLOCKED_PILOT_DIGEST``) is a separate reviewed change.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

GRANT_NAMESPACE = "sidedeck-network-unlock-grant"
SCHEMA = "sidedeck-unlock-grant/1"
BROKER = "etoro-demo"
MAX_WINDOW = {"pilot_release": timedelta(hours=8), "autonomous_policy": timedelta(days=7)}
MAX_REQUESTS = {"pilot_release": 12, "autonomous_policy": 2000}
MAX_WRITES = {"pilot_release": 2, "autonomous_policy": 200}
_HEX64 = re.compile(r"[0-9a-f]{64}")
_FIELDS = {"schema", "grant_id", "kind", "broker", "subject_digest", "not_before",
           "expires_at", "max_requests", "max_writes", "issued_by", "purpose"}

# (principal, digest, signature) -> bool; SshSignatureVerifier fits this shape.
Verifier = Callable[[str, str, str], bool]


class GrantRefused(PermissionError):
    """The grant is invalid, out of scope, expired, revoked or unsigned: stay locked."""


def _utc(text: Any, name: str) -> datetime:
    if not isinstance(text, str):
        raise GrantRefused(f"{name} must be an ISO-8601 string")
    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        raise GrantRefused(f"{name} is not a valid timestamp") from None
    if value.tzinfo is None or value.utcoffset() is None:
        raise GrantRefused(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class UnlockGrant:
    grant_id: str
    kind: str
    subject_digest: str
    not_before: datetime
    expires_at: datetime
    max_requests: int
    max_writes: int
    issued_by: str
    purpose: str
    broker: str = BROKER

    def canonical(self) -> bytes:
        document = {"schema": SCHEMA, "grant_id": self.grant_id, "kind": self.kind,
                    "broker": self.broker, "subject_digest": self.subject_digest,
                    "not_before": self.not_before.astimezone(timezone.utc).isoformat(),
                    "expires_at": self.expires_at.astimezone(timezone.utc).isoformat(),
                    "max_requests": self.max_requests, "max_writes": self.max_writes,
                    "issued_by": self.issued_by, "purpose": self.purpose}
        return json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def digest(self) -> str:
        return hashlib.sha256(self.canonical()).hexdigest()

    @classmethod
    def from_document(cls, document: Any) -> "UnlockGrant":
        """Strict parse: exact field set, exact types, bounded scope."""
        if not isinstance(document, dict) or set(document) != _FIELDS:
            raise GrantRefused("grant must contain exactly the schema fields")
        if document["schema"] != SCHEMA:
            raise GrantRefused("unknown grant schema")
        grant = cls(grant_id=document["grant_id"], kind=document["kind"],
                    subject_digest=document["subject_digest"],
                    not_before=_utc(document["not_before"], "not_before"),
                    expires_at=_utc(document["expires_at"], "expires_at"),
                    max_requests=document["max_requests"], max_writes=document["max_writes"],
                    issued_by=document["issued_by"], purpose=document["purpose"],
                    broker=document["broker"])
        grant.check_scope()
        return grant

    def check_scope(self) -> None:
        try:
            canonical_id = str(uuid.UUID(str(self.grant_id)))
        except ValueError:
            raise GrantRefused("grant_id must be a UUID") from None
        if canonical_id != self.grant_id:
            raise GrantRefused("grant_id must be a canonical lowercase UUID")
        if self.broker != BROKER:
            raise GrantRefused("only eToro Demo can be unlocked; Real is permanently excluded")
        if self.kind not in MAX_WINDOW:
            raise GrantRefused("unknown grant kind")
        if not isinstance(self.subject_digest, str) or not _HEX64.fullmatch(self.subject_digest):
            raise GrantRefused("subject_digest must be one 64-hex digest")
        for name, cap in (("max_requests", MAX_REQUESTS[self.kind]),
                          ("max_writes", MAX_WRITES[self.kind])):
            value = getattr(self, name)
            if type(value) is not int or not 0 < value <= cap:
                raise GrantRefused(f"{name} must be a positive integer <= {cap}")
        if self.max_writes > self.max_requests:
            raise GrantRefused("max_writes cannot exceed max_requests")
        window = self.expires_at - self.not_before
        if not timedelta(0) < window <= MAX_WINDOW[self.kind]:
            raise GrantRefused("grant window must be positive and within the kind's maximum")
        if not isinstance(self.issued_by, str) or not self.issued_by:
            raise GrantRefused("issued_by is required")
        if not isinstance(self.purpose, str) or not 0 < len(self.purpose) <= 500:
            raise GrantRefused("purpose must be 1-500 characters")


def require_pinned_signer(path: Path, principal: str, key_sha256: str) -> None:
    """The signers file must hold exactly one ed25519 key for the principal, the pinned one."""
    if not path.is_file() or path.is_symlink():
        raise GrantRefused("allowed_signers must be a regular file")
    lines = [line.split() for line in path.read_text(encoding="utf-8").splitlines()
             if line.strip() and not line.lstrip().startswith("#")]
    if (len(lines) != 1 or len(lines[0]) < 3 or lines[0][0] != principal
            or lines[0][1] != "ssh-ed25519"
            or hashlib.sha256(lines[0][2].encode("ascii")).hexdigest() != key_sha256):
        raise GrantRefused("allowed_signers does not hold exactly the pinned owner key")


class GrantLedger:
    """Append-only, hash-chained audit ledger of grant events."""

    def __init__(self, path: str) -> None:
        if path.strip() in ("", ":memory:") or path.startswith("file:"):
            raise GrantRefused("the grant ledger must be a durable file")
        self._db = sqlite3.connect(Path(path), isolation_level=None)
        self._db.execute("CREATE TABLE IF NOT EXISTS unlock_grant_events (seq INTEGER PRIMARY "
                         "KEY AUTOINCREMENT, at TEXT NOT NULL, grant_id TEXT NOT NULL, "
                         "grant_digest TEXT NOT NULL, event TEXT NOT NULL, detail TEXT NOT NULL,"
                         " prev_hash TEXT NOT NULL, hash TEXT NOT NULL)")

    def close(self) -> None:
        self._db.close()

    @staticmethod
    def _hash(prev: str, at: str, grant_id: str, grant_digest: str, event: str,
              detail: str) -> str:
        return hashlib.sha256("\x1f".join((prev, at, grant_id, grant_digest, event, detail))
                              .encode("utf-8")).hexdigest()

    def append(self, grant_id: str, grant_digest: str, event: str, detail: str = "") -> None:
        self._db.execute("BEGIN IMMEDIATE")
        try:
            row = self._db.execute("SELECT hash FROM unlock_grant_events ORDER BY seq DESC "
                                   "LIMIT 1").fetchone()
            prev = "0" * 64 if row is None else str(row[0])
            at = datetime.now(timezone.utc).isoformat()
            self._db.execute("INSERT INTO unlock_grant_events (at, grant_id, grant_digest, "
                             "event, detail, prev_hash, hash) VALUES (?, ?, ?, ?, ?, ?, ?)",
                             (at, grant_id, grant_digest, event, detail, prev,
                              self._hash(prev, at, grant_id, grant_digest, event, detail)))
            self._db.execute("COMMIT")
        except BaseException:
            if self._db.in_transaction:
                self._db.execute("ROLLBACK")
            raise

    def events(self, grant_id: str | None = None) -> list[tuple[str, str, str]]:
        rows = self._db.execute("SELECT grant_id, event, detail FROM unlock_grant_events "
                                "ORDER BY seq").fetchall()
        return [(str(r[0]), str(r[1]), str(r[2])) for r in rows
                if grant_id is None or r[0] == grant_id]

    def revoked(self, grant_id: str) -> bool:
        return any(event == "REVOKED" for _, event, _ in self.events(grant_id))

    def verify_chain(self) -> bool:
        prev, expected_seq = "0" * 64, 1
        for seq, at, gid, gdig, event, detail, prev_hash, digest in self._db.execute(
                "SELECT seq, at, grant_id, grant_digest, event, detail, prev_hash, hash FROM "
                "unlock_grant_events ORDER BY seq"):
            if (seq != expected_seq or prev_hash != prev
                    or digest != self._hash(prev, at, gid, gdig, event, detail)):
                return False
            prev, expected_seq = digest, expected_seq + 1
        return True


class UnlockAuthority:
    """Decides whether the order network may open for one subject digest, right now."""

    def __init__(self, *, verifier: Verifier, principal: str, ledger: GrantLedger) -> None:
        if getattr(verifier, "namespace", None) != GRANT_NAMESPACE:
            raise GrantRefused("grants must be verified in the unlock-grant namespace")
        self._verify, self._principal, self._ledger = verifier, principal, ledger

    def check(self, *, document: Any, signature: str, subject_digest: str,
              now: datetime | None = None) -> UnlockGrant:
        """Return the verified, active grant for ``subject_digest`` or raise GrantRefused.
        Every outcome is written to the audit ledger."""
        moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        grant_id = str(document.get("grant_id", "?")) if isinstance(document, dict) else "?"
        try:
            grant = UnlockGrant.from_document(document)
            if grant.issued_by != self._principal:
                raise GrantRefused("grant must be issued by the owner principal")
            if not self._ledger.verify_chain():
                raise GrantRefused("grant audit ledger failed its integrity check")
            if self._ledger.revoked(grant.grant_id):
                raise GrantRefused("grant has been revoked")
            if not self._verify(self._principal, grant.digest(), signature):
                raise GrantRefused("owner signature does not verify for this exact grant")
            if grant.subject_digest != subject_digest:
                raise GrantRefused("grant does not cover this subject")
            if not grant.not_before <= moment < grant.expires_at:
                raise GrantRefused("grant is outside its signed window")
        except GrantRefused as exc:
            self._ledger.append(grant_id, "-", "REFUSED", str(exc))
            raise
        self._ledger.append(grant.grant_id, grant.digest(), "ACTIVE_CHECK_PASSED",
                            f"subject={subject_digest} kind={grant.kind}")
        return grant

    def revoke(self, grant_id: str, reason: str) -> None:
        """Permanent; anyone may revoke (it only removes privilege)."""
        self._ledger.append(grant_id, "-", "REVOKED", reason or "revoked")
