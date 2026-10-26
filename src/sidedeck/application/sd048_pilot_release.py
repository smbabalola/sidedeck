"""SD-048 (C8) one-time, externally signed eToro Demo pilot release control.

The owner signs the SHA-256 digest of a canonical ``PilotIntent`` with their own SSH
key (SD-045, namespace ``sidedeck-paper-approval``). A ``PilotRelease`` is issued only
when **all** of the following hold; a valid signature alone is never enough:

* intent bounds: eToro Demo only; caps within the per-route ceilings and at most
  15 requests / 2 writes in total (enforced again at runtime by ``PilotBudget``);
  notional <= USD 50; limit <= +0.5 % over reference; window <= 8 h;
* scope rules: strategy book, instrument not in the protected baseline;
* independent gates: single-pair credential policy accepted, baseline MATCHED,
  kill-switch clear, pilot budget unused, signers file configured;
* the signature verifies for the configured principal over the exact digest;
* single use: each pilot id and digest is consumed once (replay refused).

``ETORO_DEMO_EXECUTION_RELEASE`` stays ``NO_GO``; a release is a narrow, expiring,
single-pilot exception checked again by the desk and the transport. This module makes
no network request.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from sidedeck.application.sd036_etoro_demo_desk import BrokerExecutionDisabled
from sidedeck.application.sd042_etoro_credential_roles import POLICY as CREDENTIAL_POLICY
from sidedeck.application.sd042_etoro_credential_roles import assess_roles
from sidedeck.application.sd045_ssh_approval_verifier import SshSignatureVerifier
from sidedeck.application.sd046_etoro_demo_pilot import (
    MAX_NOTIONAL_USD, MAX_PLANNING_HEADROOM, SD044_CAPS, PilotError, PilotScope, check_caps,
)
from sidedeck.domain.etoro_demo_books import BaselinePosition

MAX_WINDOW = timedelta(hours=8)
# Dedicated namespace: a per-order SD-033 approval signature can never act as a pilot release.
PILOT_NAMESPACE = "sidedeck-etoro-pilot-release"
_TOKEN = object()


class PilotReleaseRefused(PermissionError):
    """A release gate failed; no release was issued and nothing was consumed."""


def _utc(value: datetime, what: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise PilotReleaseRefused(f"{what} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class PilotIntent:
    pilot_id: str
    strategy: str
    instrument_id: int
    units: Decimal
    max_limit_rate: Decimal          # ceiling; the actual limit is <= +0.5 % over a fresh ask
    reference_price: Decimal
    max_notional_usd: Decimal
    not_before: datetime
    expires_at: datetime
    request_caps: tuple[tuple[str, int], ...] = field(
        default_factory=lambda: tuple(sorted(SD044_CAPS.items())))
    broker: str = "etoro-demo"

    def canonical(self) -> bytes:
        document = {"broker": self.broker, "pilot_id": self.pilot_id, "strategy": self.strategy,
                    "instrument_id": self.instrument_id, "units": str(self.units),
                    "max_limit_rate": str(self.max_limit_rate),
                    "reference_price": str(self.reference_price),
                    "max_notional_usd": str(self.max_notional_usd),
                    "not_before": _utc(self.not_before, "not_before").isoformat(),
                    "expires_at": _utc(self.expires_at, "expires_at").isoformat(),
                    "request_caps": dict(self.request_caps), "schema": "sidedeck-pilot-intent/2"}
        return json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def digest(self) -> str:
        return hashlib.sha256(self.canonical()).hexdigest()

    def scope(self) -> PilotScope:
        return PilotScope(self.strategy, self.instrument_id, self.units, self.max_limit_rate,
                          self.reference_price)


@dataclass(frozen=True)
class ReleaseGates:
    credential_status: str
    baseline_status: str
    kill_switch_clear: bool
    pilot_budget_unused: bool
    signers_configured: bool

    def failures(self) -> list[str]:
        failed = []
        if self.credential_status != CREDENTIAL_POLICY:
            failed.append("CREDENTIAL_POLICY")
        if self.baseline_status != "MATCHED":
            failed.append("BASELINE_NOT_MATCHED")
        if not self.kill_switch_clear:
            failed.append("KILL_SWITCH_ACTIVE")
        if not self.pilot_budget_unused:
            failed.append("PILOT_BUDGET_USED")
        if not self.signers_configured:
            failed.append("SIGNERS_NOT_CONFIGURED")
        return failed

    @classmethod
    def from_runtime(cls, *, env: Any, controls: Any, pilot_budget: Any, baseline_status: str,
                     signers_path: str) -> "ReleaseGates":
        """Compute the gates from live objects rather than caller-asserted booleans."""
        signers = Path(signers_path)
        return cls(credential_status=assess_roles(env)["status"], baseline_status=baseline_status,
                   kill_switch_clear=not controls.is_halted(),
                   pilot_budget_unused=sum(pilot_budget.usage().values()) == 0,
                   signers_configured=signers.is_file() and not signers.is_symlink())


class PilotRelease:
    """Issued only by ``authorize_pilot``. Expiring and bound to one intent digest."""

    __slots__ = ("intent", "digest", "issued_at")
    intent: PilotIntent
    digest: str
    issued_at: datetime

    def __init__(self, token: object, intent: PilotIntent, issued_at: datetime) -> None:
        if token is not _TOKEN:
            raise BrokerExecutionDisabled("a pilot release can only be issued by authorize_pilot")
        object.__setattr__(self, "intent", intent)
        object.__setattr__(self, "digest", intent.digest())
        object.__setattr__(self, "issued_at", issued_at)

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("PilotRelease is immutable")

    def require_active(self, now: datetime | None = None) -> None:
        moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        start = _utc(self.intent.not_before, "not_before")
        end = _utc(self.intent.expires_at, "expires_at")
        if not start <= moment < end:
            raise BrokerExecutionDisabled("pilot release is outside its signed time window")
        if self.digest != self.intent.digest():
            raise BrokerExecutionDisabled("pilot release no longer matches its intent")


class PilotReleaseStore:
    """Single-use ledger: each pilot id and digest may be consumed exactly once."""

    def __init__(self, path: str) -> None:
        if path.strip() in ("", ":memory:") or path.startswith("file:"):
            raise PilotReleaseRefused("the single-use ledger must be a durable file")
        self._db = sqlite3.connect(Path(path), isolation_level=None)
        self._db.execute("CREATE TABLE IF NOT EXISTS sd048_pilot_releases (pilot_id TEXT "
                         "PRIMARY KEY, digest TEXT NOT NULL UNIQUE, consumed_at TEXT NOT NULL)")

    def close(self) -> None:
        self._db.close()

    def consume(self, intent: PilotIntent, now: datetime) -> None:
        try:
            self._db.execute("INSERT INTO sd048_pilot_releases VALUES (?, ?, ?)",
                             (intent.pilot_id, intent.digest(), now.isoformat()))
        except sqlite3.IntegrityError as exc:
            raise PilotReleaseRefused("pilot release already used (replay refused)") from exc

    def used(self) -> int:
        return int(self._db.execute("SELECT COUNT(*) FROM sd048_pilot_releases").fetchone()[0])


def _check_intent(intent: PilotIntent, now: datetime) -> None:
    try:
        canonical_id = str(uuid.UUID(intent.pilot_id))
    except (ValueError, TypeError, AttributeError):
        raise PilotReleaseRefused("pilot id must be a UUID") from None
    if canonical_id != intent.pilot_id:
        raise PilotReleaseRefused("pilot id must be a canonical lowercase UUID")
    if (type(intent.strategy) is not str or type(intent.instrument_id) is not int
            or intent.instrument_id <= 0):
        raise PilotReleaseRefused("strategy and instrument id have invalid types")
    if intent.broker != "etoro-demo":
        raise PilotReleaseRefused("only eToro Demo pilots can be released")
    try:
        check_caps(dict(intent.request_caps))
    except PilotError as exc:
        raise PilotReleaseRefused(str(exc)) from None
    for name in ("units", "max_limit_rate", "reference_price", "max_notional_usd"):
        value = getattr(intent, name)
        if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
            raise PilotReleaseRefused(f"{name} must be a positive Decimal")
    if intent.max_notional_usd > MAX_NOTIONAL_USD:
        raise PilotReleaseRefused("notional cap exceeds USD 50")
    if intent.units * intent.max_limit_rate > intent.max_notional_usd:
        raise PilotReleaseRefused("units x max limit exceeds the signed notional cap")
    if intent.max_limit_rate > intent.reference_price * (1 + MAX_PLANNING_HEADROOM):
        raise PilotReleaseRefused("max limit exceeds the 5 % planning headroom over reference")
    start, end = _utc(intent.not_before, "not_before"), _utc(intent.expires_at, "expires_at")
    if not start < end or end - start > MAX_WINDOW:
        raise PilotReleaseRefused("signed window must be positive and at most 8 hours")
    if not start <= now < end:
        raise PilotReleaseRefused("now is outside the signed window")


def authorize_pilot(*, intent: PilotIntent, signature: str, principal: str,
                    verifier: SshSignatureVerifier, gates: ReleaseGates,
                    baseline: tuple[BaselinePosition, ...], store: PilotReleaseStore,
                    now: datetime | None = None) -> PilotRelease:
    """Issue a single-use release only if every independent gate and the signature pass."""
    moment = _utc(now or datetime.now(timezone.utc), "now")
    if not isinstance(verifier, SshSignatureVerifier) or verifier.namespace != PILOT_NAMESPACE:
        raise PilotReleaseRefused("pilot releases need the SSH verifier with the pilot namespace")
    _check_intent(intent, moment)
    try:
        intent.scope().validate(baseline)
    except PilotError as exc:
        raise PilotReleaseRefused(str(exc)) from None
    failed = gates.failures()
    if failed:
        raise PilotReleaseRefused("release gates failed: " + ",".join(failed))
    if not verifier(principal, intent.digest(), signature):
        raise PilotReleaseRefused("owner signature does not verify for this exact intent")
    store.consume(intent, moment)
    return PilotRelease(_TOKEN, intent, moment)
