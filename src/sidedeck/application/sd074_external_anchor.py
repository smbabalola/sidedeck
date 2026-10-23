"""SD-074D off-machine checkpoint check for the SD-063 policy ledger (offline building block).

Implements the verification half of ``docs/SD074_OFF_MACHINE_ANCHOR_DESIGN.md``. After each
committed transaction the ledger's (count, head) is published as a device-MAC'd checkpoint to a
**write-once** store the trading host cannot rewrite. Checkpoints form a chain (each names the
previous checkpoint's count and head), starting with a genesis checkpoint published when the
ledger is created. Before use the keeper verifies the whole published chain by content (never by
file name) and requires the local ledger to contain the latest published head at the published
position. Rollback to an older consistent ledger+anchor pair, deleting both and starting fresh,
substituting a forged pair, or replaying an old checkpoint as the latest is refused; so is any
failure to reach the store. ``require_published`` is the publish-before-send gate the order
transport must call (SD-074F), so a proposal can never be sent from unpublished ledger state.

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

from sidedeck.application.sd063_autonomous_demo_policy import GENESIS, PolicyLedger, PolicyRefused

_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
_HEX64 = re.compile(r"[0-9a-f]{64}")
_NAME = re.compile(r"(?P<id>[a-z0-9][a-z0-9_-]{0,63})\.(?P<count>[0-9]{12})\.json")
_FIELDS = {"ledger_id", "policy_digest", "count", "head", "prev_count", "prev_head", "at", "mac"}


@dataclass(frozen=True)
class Checkpoint:
    ledger_id: str
    policy_digest: str
    count: int
    head: str
    prev_count: int          # -1 for the genesis checkpoint
    prev_head: str
    at: str
    mac: str

    def body(self) -> bytes:
        data = asdict(self)
        del data["mac"]
        return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")


class ExternalAnchor(Protocol):
    def history(self, ledger_id: str) -> list[Checkpoint]: ...
    def append(self, checkpoint: Checkpoint) -> None: ...


class WriteOnceDirectoryAnchor:
    """Offline stand-in for an off-machine write-once log: one exclusively-created file per
    (ledger, count); existing checkpoints are never overwritten. A real store must assign
    positions itself and forbid deletion; the keeper re-validates content either way."""

    def __init__(self, directory: Path) -> None:
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)

    def append(self, checkpoint: Checkpoint) -> None:
        if not _ID.fullmatch(checkpoint.ledger_id) or type(checkpoint.count) is not int \
                or not 0 <= checkpoint.count < 10**12:
            raise PolicyRefused("invalid checkpoint identity")
        path = self._dir / f"{checkpoint.ledger_id}.{checkpoint.count:012d}.json"
        try:
            with open(path, "x", encoding="utf-8") as handle:
                handle.write(json.dumps(asdict(checkpoint), sort_keys=True))
        except FileExistsError:
            raise PolicyRefused("checkpoint already published; the log is write-once") from None

    def history(self, ledger_id: str) -> list[Checkpoint]:
        out = []
        for path in self._dir.glob(f"{ledger_id}.*.json"):
            match = _NAME.fullmatch(path.name)
            data = json.loads(path.read_text(encoding="utf-8"))
            if match is None or not isinstance(data, dict) or set(data) != _FIELDS \
                    or match["id"] != ledger_id or data.get("count") != int(match["count"]):
                raise ValueError("checkpoint file name does not match its content")
            out.append(Checkpoint(**data))
        return out


class AnchorKeeper:
    """Publishes and checks device-MAC'd ledger checkpoints against an external anchor."""

    def __init__(self, external: ExternalAnchor, device_key: bytes) -> None:
        if not isinstance(device_key, bytes) or len(device_key) < 32:
            raise PolicyRefused("device key must be at least 32 bytes")
        self._external, self._key = external, device_key

    def _mac(self, cp: Checkpoint) -> str:
        return hmac.new(self._key, cp.body(), hashlib.sha256).hexdigest()

    def _chain(self, ledger_id: str, policy_digest: str | None = None) -> list[Checkpoint]:
        """The whole published chain, verified by content; [] when nothing is published."""
        if not _ID.fullmatch(ledger_id):
            raise PolicyRefused("invalid ledger id")
        try:
            history = sorted(self._external.history(ledger_id), key=lambda c: c.count)
        except (OSError, ValueError, TypeError, KeyError):
            raise PolicyRefused("external anchor unavailable; failing closed") from None
        prev_count, prev_head = -1, ""
        for cp in history:
            if type(cp.mac) is not str or not _HEX64.fullmatch(cp.mac) \
                    or not hmac.compare_digest(self._mac(cp), cp.mac) \
                    or cp.ledger_id != ledger_id or type(cp.count) is not int \
                    or type(cp.head) is not str or not _HEX64.fullmatch(cp.head):
                raise PolicyRefused("external checkpoint is not authentic")
            if (cp.prev_count, cp.prev_head) != (prev_count, prev_head) or cp.count <= prev_count:
                raise PolicyRefused("external checkpoint chain is broken (replayed or missing)")
            if policy_digest is not None and cp.policy_digest != policy_digest:
                raise PolicyRefused("external checkpoint belongs to a different policy")
            prev_count, prev_head = cp.count, cp.head
        if history and (history[0].count, history[0].head) != (0, GENESIS):
            raise PolicyRefused("external checkpoint chain does not start at genesis")
        return history

    @staticmethod
    def _local(ledger: PolicyLedger) -> tuple[int, str]:
        with ledger.transaction():                   # also re-verifies the local chain+anchor
            return ledger._head()

    @staticmethod
    def _hash_at(ledger: PolicyLedger, position: int) -> str | None:
        if position == 0:
            return GENESIS
        row = ledger._conn.execute("SELECT hash FROM events ORDER BY seq LIMIT 1 OFFSET ?",
                                   (position - 1,)).fetchone()
        return None if row is None else str(row[0])

    def verify(self, ledger: PolicyLedger, ledger_id: str) -> None:
        """Refuse if the ledger is unpublished, behind, diverged, or not the published one."""
        chain = self._chain(ledger_id, ledger.policy_digest)
        count, _ = self._local(ledger)
        if not chain:
            if count:
                raise PolicyRefused("ledger has events but no published checkpoint")
            return
        latest = chain[-1]
        if count < latest.count:
            raise PolicyRefused("local ledger is behind its published checkpoint (rollback or "
                                "deletion)")
        if self._hash_at(ledger, latest.count) != latest.head:
            raise PolicyRefused("local ledger diverges from its published checkpoint "
                                "(replaced or forged)")

    def require_no_history(self, ledger_id: str) -> None:
        """Call before creating a fresh ledger: a published history means one was deleted."""
        if self._chain(ledger_id):
            raise PolicyRefused("a published checkpoint exists for this ledger; refusing a "
                                "fresh start")

    def initialize(self, ledger: PolicyLedger, ledger_id: str, at: datetime) -> Checkpoint:
        """Publish the genesis checkpoint of a newly created, empty ledger."""
        self.require_no_history(ledger_id)
        if self._local(ledger) != (0, GENESIS):
            raise PolicyRefused("genesis can only be published for an empty ledger")
        return self._append(ledger, ledger_id, 0, GENESIS, (-1, ""), at)

    def publish(self, ledger: PolicyLedger, ledger_id: str, at: datetime) -> Checkpoint:
        """Verify, then publish the current (count, head) if it advanced."""
        self.verify(ledger, ledger_id)
        chain = self._chain(ledger_id, ledger.policy_digest)
        if not chain:
            raise PolicyRefused("publish the genesis checkpoint first (initialize)")
        count, head = self._local(ledger)
        latest = chain[-1]
        if latest.count == count:
            return latest
        return self._append(ledger, ledger_id, count, head, (latest.count, latest.head), at)

    def require_published(self, ledger: PolicyLedger, ledger_id: str) -> None:
        """Publish-before-send gate: every committed ledger event must already be published."""
        self.verify(ledger, ledger_id)
        count, _ = self._local(ledger)
        if self._chain(ledger_id, ledger.policy_digest)[-1].count != count:
            raise PolicyRefused("unpublished ledger state; publish before sending")

    def _append(self, ledger: PolicyLedger, ledger_id: str, count: int, head: str,
                prev: tuple[int, str], at: datetime) -> Checkpoint:
        unsigned = Checkpoint(ledger_id, ledger.policy_digest, count, head, prev[0], prev[1],
                              at.astimezone(timezone.utc).isoformat(), "")
        cp = Checkpoint(**{**asdict(unsigned), "mac": self._mac(unsigned)})
        try:
            self._external.append(cp)
        except OSError:
            raise PolicyRefused("external anchor unavailable; failing closed") from None
        return cp
