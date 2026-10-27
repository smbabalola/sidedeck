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
  SQLite ledger mirrored by an independent anchor file (count, head hash, revoked ids);
  edits, deletions and truncation fail closed, and a revocation in either store holds.
  Revocation is always allowed (it only reduces privilege) and is permanent.
* **Usage:** every authorized request is counted persistently against the signed caps
  (survives restarts); a write reference id is single-use (no replay / duplicate order).
* **Threat model:** local anchoring defeats accidental or partial tampering and log
  truncation; an attacker able to rewrite *both* the ledger and the anchor consistently is
  bounded only by the short signed windows (8 h / 7 days) and the per-grant caps.

This module grants nothing on its own and is not yet consulted by the order transport;
wiring it in (replacing ``UNLOCKED_PILOT_DIGEST``) is a separate reviewed change.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from sidedeck.application.sd145_audit_journal import AuditJournal

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
    """Append-only, hash-chained audit ledger of grant events with an independent anchor.

    The anchor is a separate JSON file (keep it outside the repository and data folder)
    mirroring the ledger's event count, head hash and every revoked grant id. A ledger that
    was truncated, replaced or deleted no longer matches its anchor and fails closed; a
    revocation recorded in either store stays effective (deny-by-default union).
    """

    def __init__(self, path: str, *, anchor_path: str) -> None:
        if path.strip() in ("", ":memory:") or path.startswith("file:"):
            raise GrantRefused("the grant ledger must be a durable file")
        if not anchor_path or Path(anchor_path).resolve() == Path(path).resolve():
            raise GrantRefused("the grant ledger needs a separate anchor file")
        self._anchor = Path(anchor_path)
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

    # ---- anchor ---------------------------------------------------------------------
    def _read_anchor(self) -> dict[str, Any] | None:
        if not self._anchor.exists():
            return None
        try:
            data = json.loads(self._anchor.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise GrantRefused("grant anchor is unreadable") from None
        if (not isinstance(data, dict) or type(data.get("count")) is not int
                or not isinstance(data.get("head"), str)
                or not isinstance(data.get("revoked"), list)):
            raise GrantRefused("grant anchor is malformed")
        return data

    def _write_anchor(self, count: int, head: str, revoked: set[str]) -> None:
        self._anchor.parent.mkdir(parents=True, exist_ok=True)
        temp = self._anchor.with_name(self._anchor.name + ".tmp")
        temp.write_text(json.dumps({"count": count, "head": head,
                                    "revoked": sorted(revoked)}), encoding="utf-8")
        os.replace(temp, self._anchor)

    def _head(self) -> tuple[int, str]:
        row = self._db.execute("SELECT seq, hash FROM unlock_grant_events ORDER BY seq DESC "
                               "LIMIT 1").fetchone()
        return (0, "0" * 64) if row is None else (int(row[0]), str(row[1]))

    # ---- writes ---------------------------------------------------------------------
    def _insert(self, grant_id: str, grant_digest: str, event: str, detail: str) -> None:
        _, prev = self._head()
        at = datetime.now(timezone.utc).isoformat()
        self._db.execute("INSERT INTO unlock_grant_events (at, grant_id, grant_digest, "
                         "event, detail, prev_hash, hash) VALUES (?, ?, ?, ?, ?, ?, ?)",
                         (at, grant_id, grant_digest, event, detail, prev,
                          self._hash(prev, at, grant_id, grant_digest, event, detail)))

    def _transaction(self, body: Callable[[], None]) -> None:
        self._db.execute("BEGIN IMMEDIATE")
        try:
            if not self._consistent():
                raise GrantRefused("grant audit ledger failed its integrity check")
            body()
            anchor = self._read_anchor()
            revoked = set(anchor["revoked"]) if anchor else set()
            revoked |= {g for g, e, _ in self.events() if e == "REVOKED"}
            count, head = self._head()
            self._write_anchor(count, head, revoked)
            self._db.execute("COMMIT")
        except BaseException:
            if self._db.in_transaction:
                self._db.execute("ROLLBACK")
            raise

    def append(self, grant_id: str, grant_digest: str, event: str, detail: str = "") -> None:
        self._transaction(lambda: self._insert(grant_id, grant_digest, event, detail))

    def reserve_use(self, grant: "UnlockGrant", *, write: bool, reference_id: str) -> None:
        """Count one request against the grant's signed caps, persistently and atomically.
        A write reference may be used once only (no replay, no duplicate order)."""
        if not isinstance(reference_id, str) or not reference_id:
            raise GrantRefused("a reference id is required")

        def body() -> None:
            uses = [(e, d) for g, e, d in self.events(grant.grant_id)
                    if e in ("USE_READ", "USE_WRITE")]
            if len(uses) >= grant.max_requests:
                raise GrantRefused("grant request cap exhausted")
            if write:
                writes = [d for e, d in uses if e == "USE_WRITE"]
                if len(writes) >= grant.max_writes:
                    raise GrantRefused("grant write cap exhausted")
                if reference_id in writes:
                    raise GrantRefused("write reference already used (replay refused)")
            self._insert(grant.grant_id, grant.digest(), "USE_WRITE" if write else "USE_READ",
                         reference_id)
        self._transaction(body)

    # ---- reads ----------------------------------------------------------------------
    def events(self, grant_id: str | None = None) -> list[tuple[str, str, str]]:
        rows = self._db.execute("SELECT grant_id, event, detail FROM unlock_grant_events "
                                "ORDER BY seq").fetchall()
        return [(str(r[0]), str(r[1]), str(r[2])) for r in rows
                if grant_id is None or r[0] == grant_id]

    def revoked(self, grant_id: str) -> bool:
        anchor = self._read_anchor()
        return (any(event == "REVOKED" for _, event, _ in self.events(grant_id))
                or (anchor is not None and grant_id in anchor["revoked"]))

    def _chain_ok(self) -> bool:
        prev, expected_seq = "0" * 64, 1
        for seq, at, gid, gdig, event, detail, prev_hash, digest in self._db.execute(
                "SELECT seq, at, grant_id, grant_digest, event, detail, prev_hash, hash FROM "
                "unlock_grant_events ORDER BY seq"):
            if (seq != expected_seq or prev_hash != prev
                    or digest != self._hash(prev, at, gid, gdig, event, detail)):
                return False
            prev, expected_seq = digest, expected_seq + 1
        return True

    def _consistent(self) -> bool:
        if not self._chain_ok():
            return False
        count, head = self._head()
        anchor = self._read_anchor()
        if anchor is None:
            return count == 0                    # a populated ledger without its anchor
        return bool(anchor["count"] == count and anchor["head"] == head)

    def verify_chain(self) -> bool:
        """Chain intact AND equal to the independent anchor (detects truncation)."""
        try:
            return self._consistent()
        except GrantRefused:
            return False


class UnlockAuthority:
    """Decides whether the order network may open for one subject digest, right now."""

    def __init__(self, *, verifier: Verifier, principal: str, ledger: GrantLedger,
                 audit_journal: AuditJournal | None = None) -> None:
        if getattr(verifier, "namespace", None) != GRANT_NAMESPACE:
            raise GrantRefused("grants must be verified in the unlock-grant namespace")
        self._verify, self._principal, self._ledger = verifier, principal, ledger
        self._audit_journal = audit_journal

    def bind_audit_journal(self, audit_journal: AuditJournal) -> None:
        """Bind the route's mandatory anchored journal for future grant use/revocation."""
        if self._audit_journal is not None and self._audit_journal is not audit_journal:
            raise GrantRefused("unlock authority is already bound to another audit journal")
        self._audit_journal = audit_journal

    def _validate(self, document: Any, signature: str, subject_digest: str,
                  moment: datetime) -> UnlockGrant:
        grant = UnlockGrant.from_document(document)
        if self._audit_journal is not None:
            try:
                self._audit_journal.verify()
            except Exception:
                raise GrantRefused("external grant audit anchor is unavailable or inconsistent") \
                    from None
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
        return grant

    def _refuse(self, document: Any, exc: GrantRefused) -> None:
        grant_id = str(document.get("grant_id", "?")) if isinstance(document, dict) else "?"
        try:
            self._ledger.append(grant_id, "-", "REFUSED", str(exc))
        except GrantRefused:
            pass                                  # an inconsistent ledger still refuses

    def check(self, *, document: Any, signature: str, subject_digest: str,
              now: datetime | None = None) -> UnlockGrant:
        """Return the verified, active grant for ``subject_digest`` or raise GrantRefused.
        Every outcome is written to the audit ledger."""
        moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        try:
            grant = self._validate(document, signature, subject_digest, moment)
        except GrantRefused as exc:
            self._refuse(document, exc)
            raise
        self._ledger.append(grant.grant_id, grant.digest(), "ACTIVE_CHECK_PASSED",
                            f"subject={subject_digest} kind={grant.kind}")
        if self._audit_journal is not None:
            self._audit_journal.append("GRANT", entity_id=grant.grant_id,
                                       payload={"digest": grant.digest(), "kind": grant.kind,
                                                "subject_digest": subject_digest}, at=moment)
        return grant

    def authorize_request(self, *, document: Any, signature: str, subject_digest: str,
                          write: bool, reference_id: str,
                          now: datetime | None = None) -> UnlockGrant:
        """Full gate for ONE broker request: valid, in window, not revoked, within the
        persistent signed caps; a write reference is single-use."""
        moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        try:
            grant = self._validate(document, signature, subject_digest, moment)
            self._ledger.reserve_use(grant, write=write, reference_id=reference_id)
            if self._audit_journal is not None:
                self._audit_journal.append(
                    "GRANT_USE", entity_id=grant.grant_id,
                    payload={"grant_digest": grant.digest(), "write": write,
                             "reference_id": reference_id,
                             "subject_digest": subject_digest}, at=moment)
        except GrantRefused as exc:
            self._refuse(document, exc)
            raise
        return grant

    def revoke(self, grant_id: str, reason: str) -> None:
        """Permanent; anyone may revoke (it only removes privilege)."""
        self._ledger.append(grant_id, "-", "REVOKED", reason or "revoked")
        if self._audit_journal is not None:
            self._audit_journal.append("REVOCATION", entity_id=grant_id,
                                       payload={"reason": reason or "revoked"},
                                       at=datetime.now(timezone.utc))


# ---- owner tooling: prepare a grant for signing (never signs) ---------------------------
OWNER_PRINCIPAL = "owner@sidedeck"


def prepare_grant(folder: Path, *, kind: str, subject_digest: str, not_before: str,
                  expires_at: str, max_requests: int, max_writes: int,
                  purpose: str) -> dict[str, str]:
    """Write ``<grant_id>.json`` (canonical) and ``<grant_id>.digest`` for the owner to sign.
    Scope rules are enforced before anything is written; nothing is signed here."""
    document = {"schema": SCHEMA, "grant_id": str(uuid.uuid4()), "kind": kind,
                "broker": BROKER, "subject_digest": subject_digest, "not_before": not_before,
                "expires_at": expires_at, "max_requests": max_requests,
                "max_writes": max_writes, "issued_by": OWNER_PRINCIPAL, "purpose": purpose}
    grant = UnlockGrant.from_document(document)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{grant.grant_id}.json"
    path.write_bytes(grant.canonical())
    digest_path = path.with_suffix(".digest")
    digest_path.write_bytes(grant.digest().encode("ascii"))
    command = (f"if ((Get-Content -Raw '{digest_path}') -ceq '{grant.digest()}') {{ ssh-keygen "
               f"-Y sign -f \"$HOME\\.ssh\\sidedeck_approval\" -n {GRANT_NAMESPACE} "
               f"'{digest_path}' }} else {{ 'DIGEST MISMATCH - do not sign' }}")
    return {"grant_id": grant.grant_id, "grant_file": str(path), "digest": grant.digest(),
            "sign_in_powershell": command, "grants_network_access": "only once wired in and "
            "verified; this file alone authorizes nothing"}


def main(argv: list[str] | None = None) -> int:
    import argparse

    from sidedeck.application import sd050_msft_instrument_lookup as lookup

    parser = argparse.ArgumentParser(description="SD-064 prepare an owner-signed unlock grant")
    commands = parser.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("prepare", help="write a grant and its digest for signing")
    prep.add_argument("--kind", choices=sorted(MAX_WINDOW), required=True)
    prep.add_argument("--subject-digest", required=True)
    prep.add_argument("--not-before", required=True, help="ISO-8601 with offset")
    prep.add_argument("--expires-at", required=True, help="ISO-8601 with offset")
    prep.add_argument("--max-requests", type=int, required=True)
    prep.add_argument("--max-writes", type=int, required=True)
    prep.add_argument("--purpose", required=True)
    args = parser.parse_args(argv)
    try:
        result = prepare_grant(lookup.DATA_DIR / "grants", kind=args.kind,
                               subject_digest=args.subject_digest,
                               not_before=args.not_before, expires_at=args.expires_at,
                               max_requests=args.max_requests, max_writes=args.max_writes,
                               purpose=args.purpose)
    except GrantRefused as exc:
        print(json.dumps({"status": "REFUSED", "reason": str(exc)}, indent=2))
        return 5
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
