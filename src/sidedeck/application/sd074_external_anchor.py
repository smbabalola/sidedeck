"""SD-074D off-machine checkpoint check for the SD-063 policy ledger (offline building block).

Implements the verification half of ``docs/SD074_OFF_MACHINE_ANCHOR_DESIGN.md``. After each
committed transaction the ledger's (count, head) is published as a device-MAC'd checkpoint to a
**write-once** store the trading host cannot rewrite. Checkpoints form a chain (each names the
previous checkpoint's count and head), starting with a genesis checkpoint published when the
ledger is created. The chain's id is derived from the policy digest, so a policy can only ever
have one chain (no fresh restart under another id). Before use the keeper verifies the whole
published chain by content and requires the local ledger to contain the latest published head
at the published position. Rollback, deletion of both local files, a forged pair, and replayed or
inserted checkpoints are refused; so is any failure to reach the store. ``require_published`` is
the publish-before-send gate the order transport must call (SD-074F).

Requirements on the real store (not implementable by the keeper): it must forbid deletion and
truncation (a deleted latest checkpoint leaves a valid prefix the keeper cannot distinguish),
append only when its current latest equals the new checkpoint's ``prev`` (compare-and-append),
and write atomically. ``WriteOnceDirectoryAnchor`` is an offline stand-in that implements the
last two for tests; no real off-machine store exists and nothing is wired into the runtime.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from sidedeck.application.sd063_autonomous_demo_policy import GENESIS, PolicyLedger, PolicyRefused

_ID = re.compile(r"policy-[0-9a-f]{32}")
_HEX64 = re.compile(r"[0-9a-f]{64}")
_NAME = re.compile(r"(?P<id>policy-[0-9a-f]{32})\.(?P<count>[0-9]{12})\.json")
LOCK_TIMEOUT_SECONDS = 60
_FIELDS = {"ledger_id", "policy_digest", "count", "head", "prev_count", "prev_head", "at", "mac"}


def ledger_id_for(policy_digest: str) -> str:
    """The only chain id a policy can have (prevents a second chain for the same policy)."""
    if not isinstance(policy_digest, str) or not _HEX64.fullmatch(policy_digest):
        raise PolicyRefused("policy digest must be one 64-hex digest")
    return f"policy-{policy_digest[:32]}"


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
    """Offline stand-in for an off-machine write-once log with compare-and-append and atomic,
    durable writes (temp file + fsync + hard link that fails if the name exists)."""

    def __init__(self, directory: Path) -> None:
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)

    def append(self, checkpoint: Checkpoint) -> None:
        if not _ID.fullmatch(checkpoint.ledger_id) or type(checkpoint.count) is not int \
                or not 0 <= checkpoint.count < 10**12:
            raise PolicyRefused("invalid checkpoint identity")
        lock = self._dir / f"{checkpoint.ledger_id}.lock"
        self._take_lock(lock)
        try:
            try:
                history = sorted(self.history(checkpoint.ledger_id), key=lambda c: c.count)
            except (OSError, ValueError, TypeError, KeyError):
                raise PolicyRefused("external anchor unavailable; failing closed") from None
            latest = (history[-1].count, history[-1].head) if history else (-1, "")
            if latest != (checkpoint.prev_count, checkpoint.prev_head):
                raise PolicyRefused("store head moved; checkpoint does not extend it (retry)")
            final = self._dir / f"{checkpoint.ledger_id}.{checkpoint.count:012d}.json"
            tmp = self._dir / f".{final.name}.{os.getpid()}.tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(asdict(checkpoint), sort_keys=True))
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(tmp, final)                  # atomic; fails if the name exists
            except FileExistsError:
                raise PolicyRefused("checkpoint already published; the log is write-once") \
                    from None
            finally:
                tmp.unlink(missing_ok=True)
        finally:
            lock.unlink(missing_ok=True)

    @staticmethod
    def _take_lock(lock: Path) -> None:
        """Exclusive lock file stamped with its creation time; a lock older than
        ``LOCK_TIMEOUT_SECONDS`` (a crashed publisher) is broken once, then retried."""
        for attempt in (1, 2):
            try:
                fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                try:
                    stamp = float(lock.read_text(encoding="utf-8") or "0")
                except (OSError, ValueError):
                    stamp = 0.0
                if attempt == 1 and time.time() - stamp > LOCK_TIMEOUT_SECONDS:
                    lock.unlink(missing_ok=True)          # stale: its holder is gone
                    continue
                raise PolicyRefused("concurrent publish in progress; retry") from None
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(str(time.time()))
            return

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

    def _chain(self, policy_digest: str) -> list[Checkpoint]:
        """The policy's whole published chain, verified by content; [] if nothing published."""
        ledger_id = ledger_id_for(policy_digest)
        try:
            history = sorted(self._external.history(ledger_id), key=lambda c: c.count)
        except (OSError, ValueError, TypeError, KeyError):
            raise PolicyRefused("external anchor unavailable; failing closed") from None
        prev_count, prev_head = -1, ""
        for cp in history:
            if type(cp.mac) is not str or not _HEX64.fullmatch(cp.mac) \
                    or not hmac.compare_digest(self._mac(cp), cp.mac) \
                    or cp.ledger_id != ledger_id or cp.policy_digest != policy_digest \
                    or type(cp.count) is not int or type(cp.head) is not str \
                    or not _HEX64.fullmatch(cp.head):
                raise PolicyRefused("external checkpoint is not authentic")
            if (cp.prev_count, cp.prev_head) != (prev_count, prev_head) or cp.count <= prev_count:
                raise PolicyRefused("external checkpoint chain is broken (replayed or missing)")
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

    def verify(self, ledger: PolicyLedger) -> None:
        """Refuse if the ledger is unpublished, behind, diverged, or not the published one."""
        chain = self._chain(ledger.policy_digest)
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

    def require_no_history(self, policy_digest: str) -> None:
        """Call before creating a fresh ledger: a published history means one was deleted."""
        if self._chain(policy_digest):
            raise PolicyRefused("a published checkpoint exists for this policy; refusing a "
                                "fresh start")

    def initialize(self, ledger: PolicyLedger, at: datetime) -> Checkpoint:
        """Publish the genesis checkpoint of a newly created, empty ledger."""
        self.require_no_history(ledger.policy_digest)
        if self._local(ledger) != (0, GENESIS):
            raise PolicyRefused("genesis can only be published for an empty ledger")
        return self._append(ledger, 0, GENESIS, (-1, ""), at)

    def publish(self, ledger: PolicyLedger, at: datetime) -> Checkpoint:
        """Verify, then publish the current (count, head) if it advanced."""
        self.verify(ledger)
        chain = self._chain(ledger.policy_digest)
        if not chain:
            raise PolicyRefused("publish the genesis checkpoint first (initialize)")
        count, head = self._local(ledger)
        latest = chain[-1]
        if latest.count == count:
            return latest
        return self._append(ledger, count, head, (latest.count, latest.head), at)

    def require_published(self, ledger: PolicyLedger) -> None:
        """Publish-before-send gate: every committed ledger event must already be published."""
        self.verify(ledger)
        count, _ = self._local(ledger)
        if self._chain(ledger.policy_digest)[-1].count != count:
            raise PolicyRefused("unpublished ledger state; publish before sending")

    def _append(self, ledger: PolicyLedger, count: int, head: str, prev: tuple[int, str],
                at: datetime) -> Checkpoint:
        unsigned = Checkpoint(ledger_id_for(ledger.policy_digest), ledger.policy_digest, count,
                              head, prev[0], prev[1], at.astimezone(timezone.utc).isoformat(), "")
        cp = Checkpoint(**{**asdict(unsigned), "mac": self._mac(unsigned)})
        try:
            self._external.append(cp)
        except PolicyRefused:
            raise                                    # store refusals keep their reason
        except OSError:
            raise PolicyRefused("external anchor unavailable; failing closed") from None
        return cp
