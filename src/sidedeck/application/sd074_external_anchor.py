"""SD-074D off-machine checkpoint check for the SD-063 policy ledger (offline building block).

Implements the verification half of ``docs/SD074_OFF_MACHINE_ANCHOR_DESIGN.md``: after each
committed transaction the ledger's (count, head) is published as a device-MAC'd checkpoint to a
**write-once** store the trading host cannot rewrite; before use, the local ledger must still
contain the latest published head at the published position. A rollback to an older consistent
ledger+anchor pair, deleting both and starting fresh, or substituting a forged pair is detected
and refused. Any failure to reach the store also refuses (fail closed).

Not wired into the runtime and no real remote store exists yet: ``WriteOnceDirectoryAnchor`` is
an offline stand-in with write-once semantics for tests. A real off-machine store (object lock,
separate signing host or transparency log) needs owner provisioning and an independent review
before autonomous execution can be released.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from sidedeck.application.sd063_autonomous_demo_policy import PolicyLedger, PolicyRefused

_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
_HEX64 = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class Checkpoint:
    ledger_id: str
    policy_digest: str
    count: int
    head: str
    at: str
    mac: str

    def body(self) -> bytes:
        data = asdict(self)
        del data["mac"]
        return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")


class ExternalAnchor(Protocol):
    def latest(self, ledger_id: str) -> Checkpoint | None: ...
    def append(self, checkpoint: Checkpoint) -> None: ...


class WriteOnceDirectoryAnchor:
    """Offline stand-in for an off-machine write-once log: one exclusively-created file per
    (ledger, count); existing checkpoints are never overwritten."""

    def __init__(self, directory: Path) -> None:
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, ledger_id: str, count: int) -> Path:
        return self._dir / f"{ledger_id}.{count:012d}.json"

    def append(self, checkpoint: Checkpoint) -> None:
        try:
            with open(self._path(checkpoint.ledger_id, checkpoint.count), "x",
                      encoding="utf-8") as handle:
                handle.write(json.dumps(asdict(checkpoint), sort_keys=True))
        except FileExistsError:
            raise PolicyRefused("checkpoint already published; the log is write-once") from None

    def latest(self, ledger_id: str) -> Checkpoint | None:
        files = sorted(self._dir.glob(f"{ledger_id}.*.json"))
        if not files:
            return None
        return Checkpoint(**json.loads(files[-1].read_text(encoding="utf-8")))


class AnchorKeeper:
    """Publishes and checks device-MAC'd ledger checkpoints against an external anchor."""

    def __init__(self, external: ExternalAnchor, device_key: bytes) -> None:
        if not isinstance(device_key, bytes) or len(device_key) < 32:
            raise PolicyRefused("device key must be at least 32 bytes")
        self._external, self._key = external, device_key

    def _mac(self, cp: Checkpoint) -> str:
        return hmac.new(self._key, cp.body(), hashlib.sha256).hexdigest()

    def _latest(self, ledger_id: str) -> Checkpoint | None:
        if not _ID.fullmatch(ledger_id):
            raise PolicyRefused("invalid ledger id")
        try:
            cp = self._external.latest(ledger_id)
        except (OSError, ValueError, TypeError):
            raise PolicyRefused("external anchor unavailable; failing closed") from None
        if cp is not None:
            if type(cp.mac) is not str or not _HEX64.fullmatch(cp.mac) \
                    or not hmac.compare_digest(self._mac(cp), cp.mac) \
                    or cp.ledger_id != ledger_id or type(cp.count) is not int \
                    or not _HEX64.fullmatch(cp.head):
                raise PolicyRefused("external checkpoint is not authentic")
        return cp

    @staticmethod
    def _local(ledger: PolicyLedger) -> tuple[int, str]:
        with ledger.transaction():                   # also re-verifies the local chain+anchor
            return ledger._head()

    @staticmethod
    def _hash_at(ledger: PolicyLedger, position: int) -> str | None:
        if position == 0:
            return "0" * 64
        row = ledger._conn.execute("SELECT hash FROM events ORDER BY seq LIMIT 1 OFFSET ?",
                                   (position - 1,)).fetchone()
        return None if row is None else str(row[0])

    def verify(self, ledger: PolicyLedger, ledger_id: str) -> None:
        """Refuse if the local ledger is behind, diverged from, or not the published one."""
        cp = self._latest(ledger_id)
        if cp is None:
            return
        if cp.policy_digest != ledger.policy_digest:
            raise PolicyRefused("external checkpoint belongs to a different policy")
        count, _ = self._local(ledger)
        if count < cp.count:
            raise PolicyRefused("local ledger is behind its published checkpoint (rollback or "
                                "deletion)")
        if self._hash_at(ledger, cp.count) != cp.head:
            raise PolicyRefused("local ledger diverges from its published checkpoint "
                                "(replaced or forged)")

    def require_no_history(self, ledger_id: str) -> None:
        """Call before creating a fresh ledger: a published history means one was deleted."""
        if self._latest(ledger_id) is not None:
            raise PolicyRefused("a published checkpoint exists for this ledger; refusing a "
                                "fresh start")

    def publish(self, ledger: PolicyLedger, ledger_id: str, at: datetime) -> Checkpoint:
        """Verify, then publish the current (count, head) if it advanced."""
        self.verify(ledger, ledger_id)
        count, head = self._local(ledger)
        latest = self._latest(ledger_id)
        if latest is not None and latest.count == count:
            return latest
        unsigned = Checkpoint(ledger_id, ledger.policy_digest, count, head,
                              at.astimezone(timezone.utc).isoformat(), "")
        cp = Checkpoint(**{**asdict(unsigned), "mac": self._mac(unsigned)})
        try:
            self._external.append(cp)
        except OSError:
            raise PolicyRefused("external anchor unavailable; failing closed") from None
        return cp
