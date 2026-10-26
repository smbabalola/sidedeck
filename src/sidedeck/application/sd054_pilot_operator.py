"""SD-054 supervised eToro Demo pilot operator: one signed release, end to end.

Sequence (every step fails closed; nothing is retried):

1. Verify the owner's SSH signature over the SD-053 intent (namespace
   ``sidedeck-etoro-pilot-release``) and the runtime gates; consume the single-use release.
2. Build the desk with a policy equal to the signed intent and the pilot request budget.
3. Preflight (reads only): baseline MATCHED live, Demo eligibility, fresh realtime ask,
   derived limit; instrument type / currency evidence reported.
4. Print the exact open request and its SD-033 digest; the owner signs it
   (dedicated namespace ``sidedeck-etoro-pilot-approval``). Open, then confirm through
   lineage lookups.
5. Print the exact full-close request; the owner signs it separately. Close, confirm, and
   reconcile: ``COMPLETE`` only if the close FILLED, the final reconcile is MATCHED and no
   SideDeck position remains. Otherwise ``UNRESOLVED_OPERATOR_INTERVENTION_REQUIRED`` with
   the kill-switch tripped and the position left for the operator.

**Locked in this phase.** ``run_pilot`` takes a ``transport_factory``; ``main run`` uses the
transport module's single production factory, but first checks the order lock and refuses
(``REFUSED_LOCKED``) before reading any secret or consuming the release. Lifting the lock is
the separate, reviewed lock-lift commit plus the owner's explicit execution authorization.
``main verify`` checks the owner's release signature offline and consumes nothing.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from sidedeck.application.sd032_durable_paper_intent import DurablePaperIntentStore
from sidedeck.application.sd033_approval_killswitch import (
    ApprovalError, ApprovalKillSwitch, intent_digest,
)
from sidedeck.application.sd036_etoro_demo_desk import (
    DemoDeskPolicy, DemoRateBudget, EtoroDemoDesk, EtoroDemoLineage,
)
from sidedeck.application.sd045_ssh_approval_verifier import SshSignatureVerifier
from sidedeck.application.sd046_etoro_demo_pilot import (
    PILOT_OPERATOR, UNRESOLVED, EtoroDemoPilot, PilotBudget, PilotTransport,
)
from sidedeck.application.sd058_forensic_audit import PreflightAudit
from sidedeck.application.sd048_pilot_release import (
    PILOT_NAMESPACE, PilotIntent, PilotRelease, PilotReleaseStore, ReleaseGates, authorize_pilot,
)
from sidedeck.domain.etoro_demo_books import BaselinePosition

REQUESTER = "sidedeck-pilot-runner"
OPEN_APPROVAL_TTL = timedelta(minutes=5)      # the fresh quote must still be <= 5 min old
CLOSE_APPROVAL_TTL = timedelta(minutes=30)
# Enough signed window left after the open for the close prompt and 3 close-side requests.
MIN_WINDOW_REMAINING_AT_OPEN = timedelta(minutes=20)
# Enter presses without a signature file before the prompt gives up (owner can always type NO).
MAX_EMPTY_APPROVAL_PROMPTS = 20
# Dedicated namespace: a pilot approval signature is unusable for any other SideDeck approval.
APPROVAL_NAMESPACE = "sidedeck-etoro-pilot-approval"
READY = "READY_FOR_OPEN_APPROVAL"
OPENED = "OPEN_FILLED_AWAITING_CLOSE_APPROVAL"

TransportFactory = Callable[[PilotRelease, str], Any]   # desk re-checks the transport
# (label, digest, scope) -> SSH signature text, or "" to decline.
ApprovalPrompt = Callable[[str, str, str], str]


class OperatorRefused(RuntimeError):
    """Refused before any broker request."""


@dataclass(frozen=True)
class OperatorPaths:
    root: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", self.root.expanduser().resolve())

    def __getattr__(self, name: str) -> str:
        if name in ("controls", "lineage", "outbox", "rate", "budget", "releases", "ledger",
                    "audit"):
            return str(self.root / f"{name}.sqlite3")
        raise AttributeError(name)

    @property
    def report(self) -> Path:
        return self.root / "report.json"


def _approve(controls: ApprovalKillSwitch, *, intent_id: str, scope: str, principal: str,
             signature: str, ttl: timedelta) -> bool:
    if not signature.strip():
        return False
    try:
        controls.approve(f"approval-{intent_id}", intent_id, scope, REQUESTER, principal,
                         principal, signature, datetime.now(timezone.utc) + ttl)
    except ApprovalError:
        return False
    return True


def run_pilot(*, intent: PilotIntent, release_signature: str, principal: str,
              signers_path: str, env: dict[str, str], baseline: tuple[BaselinePosition, ...],
              baseline_status: str, transport_factory: TransportFactory,
              await_approval: ApprovalPrompt, paths: OperatorPaths) -> dict[str, Any]:
    paths.root.mkdir(parents=True, exist_ok=True)
    release_verifier = SshSignatureVerifier(signers_path, principal, namespace=PILOT_NAMESPACE)
    approval_verifier = SshSignatureVerifier(signers_path, principal,
                                             namespace=APPROVAL_NAMESPACE)
    controls = ApprovalKillSwitch(paths.controls, approval_verifier)
    # Scoped to this signed pilot and bound to its signed per-route and total caps.
    budget = PilotBudget(paths.budget, pilot_id=intent.pilot_id, caps=dict(intent.request_caps))
    store = PilotReleaseStore(paths.releases)
    lineage = EtoroDemoLineage(paths.lineage,
                               baseline_position_ids=[b.position_id for b in baseline],
                               baseline_order_ids=[b.order_id for b in baseline
                                                   if b.order_id is not None])
    outbox = DurablePaperIntentStore(paths.outbox)
    rate = DemoRateBudget(paths.rate)
    stores: list[Any] = [controls, budget, store, lineage, outbox, rate]
    report: dict[str, Any] = {"pilot_id": intent.pilot_id, "intent_digest": intent.digest(),
                              "execution_release": "NO_GO", "steps": []}
    wrote = False
    try:
        validate = getattr(transport_factory, "validate", None)
        if callable(validate):
            validate()          # lock + credentials, before the single-use release is consumed
        gates = ReleaseGates.from_runtime(env=env, controls=controls, pilot_budget=budget,
                                          baseline_status=baseline_status,
                                          signers_path=signers_path)
        release = authorize_pilot(intent=intent, signature=release_signature,
                                  principal=principal, verifier=release_verifier, gates=gates,
                                  baseline=baseline, store=store)
        http = transport_factory(release, paths.ledger)
        stores.append(http)
        audit = PreflightAudit(paths.audit, release.digest)
        stores.append(audit)
        transport = PilotTransport(http, budget, audit)
        desk = EtoroDemoDesk(
            outbox=outbox, controls=controls, lineage=lineage, transport=transport,
            policy=DemoDeskPolicy(intent.max_notional_usd, frozenset({intent.instrument_id}), 1),
            baseline=baseline, budget=rate, pilot_release=release)
        pilot = EtoroDemoPilot(desk=desk, transport=transport, budget=budget, controls=controls,
                               lineage=lineage, baseline=baseline, scope=intent.scope(),
                               release=release, audit=audit)

        step = pilot.preflight()
        report["steps"].append(step)
        if step["result"] != READY:
            return _finish(report, step["result"], paths)

        if intent.expires_at - datetime.now(timezone.utc) < MIN_WINDOW_REMAINING_AT_OPEN:
            return _finish(report, "ABORTED_WINDOW_TOO_SHORT", paths)        # nothing written
        request, scope = pilot.open_approval_scope()
        open_id = f"sd054-open-{intent.pilot_id}"
        report["open_request"] = {"instrument_id": request.instrument_id,
                                  "units": str(request.units),
                                  "limit_rate": str(request.limit_rate)}
        signature = await_approval("open", intent_digest(open_id, scope), scope)
        if not _approve(controls, intent_id=open_id, scope=scope, principal=principal,
                        signature=signature, ttl=OPEN_APPROVAL_TTL):
            return _finish(report, "ABORTED_OPEN_NOT_APPROVED", paths)   # nothing written
        if intent.expires_at - datetime.now(timezone.utc) < MIN_WINDOW_REMAINING_AT_OPEN:
            return _finish(report, "ABORTED_WINDOW_TOO_SHORT", paths)        # nothing written
        wrote = True
        step = pilot.open_phase(intent_id=open_id)
        report["steps"].append(step)
        if step["result"] != OPENED:
            return _finish(report, step["result"], paths)

        close_request, close_scope = pilot.close_request(str(uuid.uuid4()))
        close_id = f"sd054-close-{intent.pilot_id}"
        signature = await_approval("close", intent_digest(close_id, close_scope), close_scope)
        ttl = min(CLOSE_APPROVAL_TTL, intent.expires_at - datetime.now(timezone.utc))
        if not _approve(controls, intent_id=close_id, scope=close_scope, principal=principal,
                        signature=signature, ttl=ttl):
            if not controls.is_halted():
                controls.trip(PILOT_OPERATOR, "close not approved; pilot position remains open")
            return _finish(report, UNRESOLVED, paths,
                           reason="close not approved; position remains OPEN")
        step = pilot.close_phase(intent_id=close_id, request=close_request)
        report["steps"].append(step)
        return _finish(report, step["result"], paths)
    except BaseException as exc:
        if wrote:      # an order may exist: keep the true state, never look like "nothing"
            if not controls.is_halted():
                controls.trip(PILOT_OPERATOR, f"pilot interrupted: {type(exc).__name__}")
            _finish(report, UNRESOLVED, paths, reason=f"interrupted after the open write "
                    f"({type(exc).__name__}); the pilot position may be OPEN")
        raise
    finally:
        for item in reversed(stores):
            closer = getattr(item, "close", None)
            if callable(closer):
                closer()


def _finish(report: dict[str, Any], result: str, paths: OperatorPaths,
            **extra: Any) -> dict[str, Any]:
    report.update({"result": result, "finished_at": datetime.now(timezone.utc).isoformat(),
                   **extra})
    encoded = json.dumps(report, indent=2, default=str)
    temporary = paths.report.with_name(paths.report.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(encoded)
        handle.flush()
        import os
        os.fsync(handle.fileno())
    temporary.replace(paths.report)
    return report


def recorded_baseline_status(ledger_path: str) -> str:
    """Outcome of the last owner-authorized baseline reconcile (SD-038), read-only.
    The binding live check is the preflight reconcile before any write."""
    target = Path(ledger_path)
    if not target.is_file():
        return "UNKNOWN"
    db = sqlite3.connect(target.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        row = db.execute("SELECT outcome FROM sd038_budget").fetchone()
    finally:
        db.close()
    return "UNKNOWN" if row is None else str(row[0])


# ---- production entry point (SD-053 MSFT pilot) -------------------------------------
# Monday 2026-10-26 15:30-19:30 UTC pilot intent e7987485 (Option B: signed 15-request /
# 2-write caps, 4 quote reads), prepared after the 14:37 UTC 1ab4d2c8 stale-quote abort.
# Older digests (consumed b0be3fe2, 0e1ab7c2, 4e1cea6f, bff0fef6, 1ab4d2c8; signed but
# unused Tuesday 40ee9682) are not pinned and therefore not runnable.
PINNED_INTENT_DIGEST = "4119f25c82ea64042f9126275e69b45ca79edda70c181eb361c9c69b8671b7dd"
PRINCIPAL = "owner@sidedeck"
# SHA-256 of the owner's ssh-ed25519 public key blob in data/approval_allowed_signers
# (verified 2026-10-22). A different or additional signer key is refused.
PINNED_SIGNER_KEY_SHA256 = "600a7f7e6597cfa2f87b1f3f9891de224c4e2a18b9d534da62888158ebbae0f3"


def require_pinned_signer(path: Path) -> None:
    import hashlib
    lines = [line.split() for line in path.read_text(encoding="utf-8").splitlines()
             if line.strip() and not line.lstrip().startswith("#")]
    if (len(lines) != 1 or len(lines[0]) < 3 or lines[0][0] != PRINCIPAL
            or lines[0][1] != "ssh-ed25519"
            or hashlib.sha256(lines[0][2].encode("ascii")).hexdigest()
            != PINNED_SIGNER_KEY_SHA256):
        raise OperatorRefused("allowed_signers does not hold exactly the pinned owner key")


def _data_dir() -> Path:
    from sidedeck.application import sd050_msft_instrument_lookup as lookup
    return lookup.DATA_DIR


def load_signed_intent() -> tuple[PilotIntent, str]:
    """The reviewed SD-053 intent (never regenerated) and the owner's signature file."""
    from sidedeck.application import sd050_msft_instrument_lookup as lookup
    from sidedeck.application import sd053_msft_pilot_intent as sd053
    data = _data_dir()
    if not sd053.INTENT_PATH.is_file():
        raise OperatorRefused("SD-053 intent file is missing; it is never regenerated here")
    protected = lookup.baseline_instrument_ids(str(data / "etoro_demo.sqlite3"))
    record = sd053.prepare(sd053.INTENT_PATH, protected)   # re-verifies reviewed parameters
    if record["digest"] != PINNED_INTENT_DIGEST:
        raise OperatorRefused("intent digest differs from the reviewed SD-053 digest")
    intent = sd053.build_intent(record["pilot_id"])
    signature_path = sd053.INTENT_PATH.with_suffix(".digest.sig")
    if not signature_path.is_file():
        raise OperatorRefused("owner signature file is missing")
    return intent, signature_path.read_text(encoding="utf-8")


def verify_release_signature() -> dict[str, Any]:
    """Offline: the owner's signature over the pinned intent. Consumes nothing."""
    intent, signature = load_signed_intent()
    signers = _data_dir() / "approval_allowed_signers"
    require_pinned_signer(signers)
    verifier = SshSignatureVerifier(str(signers), PRINCIPAL, namespace=PILOT_NAMESPACE)
    now = datetime.now(timezone.utc)
    return {"intent_digest": intent.digest(), "principal": PRINCIPAL,
            "namespace": PILOT_NAMESPACE,
            "signature_valid": verifier(PRINCIPAL, intent.digest(), signature),
            "window_utc": [intent.not_before.isoformat(), intent.expires_at.isoformat()],
            "window_open_now": intent.not_before <= now < intent.expires_at,
            "release_consumed": False, "requests_sent": 0, "execution_release": "NO_GO"}


def console_approval(label: str, digest: str, scope: str) -> str:
    """Write the exact approval digest; wait for the owner's separate SSH signature."""
    folder = _data_dir() / "sd054"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{label}-approval.digest"
    signature = path.with_name(path.name + ".sig")
    if signature.exists():
        signature.unlink()                      # never pick up a stale signature
    path.write_bytes(digest.encode("ascii"))
    # The command re-checks the file against the digest shown here before signing, so a
    # swapped file is never signed; the namespace is dedicated to pilot approvals.
    command = (f"if ((Get-Content -Raw '{path}') -ceq '{digest}') {{ ssh-keygen -Y sign -f "
               f"\"$HOME\\.ssh\\sidedeck_approval\" -n {APPROVAL_NAMESPACE} '{path}' }} "
               "else { 'DIGEST MISMATCH - do not sign' }")
    print(json.dumps({"approval": label, "scope": scope, "digest": digest,
                      "sign_in_powershell": command}, indent=2))
    steps = (f"\n=== OWNER {label.upper()} APPROVAL - DO NOT press Enter yet ===\n"
             "1. Leave THIS window running.\n"
             "2. Open a SECOND PowerShell window and cd to the SideDeck folder.\n"
             "3. Paste the 'sign_in_powershell' command above there, enter your passphrase,\n"
             f"   and wait for: Write signature to ...{path.name}.sig\n"
             "4. Come back to THIS window and press Enter (type NO to decline).\n")
    print(steps, file=sys.stderr, flush=True)
    for _ in range(MAX_EMPTY_APPROVAL_PROMPTS):
        answer = input(f"[{label}] Signed in the second window? Press Enter (or NO): ")
        if answer.strip().upper() == "NO":
            return ""
        if signature.is_file():
            return signature.read_text(encoding="utf-8")
        print(f"STOP: no signature file yet at {signature}. Sign it in the SECOND PowerShell "
              "window first, then press Enter here.", file=sys.stderr, flush=True)
    return ""


def main(argv: list[str] | None = None) -> int:
    import argparse

    from sidedeck.application import sd050_msft_instrument_lookup as lookup
    from sidedeck.infrastructure import etoro_demo_write_transport as wt
    from sidedeck.infrastructure.etoro_demo_store import EtoroDemoStore

    parser = argparse.ArgumentParser(description="SD-054 supervised eToro Demo MSFT pilot")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("verify", help="verify the owner's release signature (offline)")
    run = commands.add_parser("run", help="execute the signed pilot (needs the lock lifted)")
    run.add_argument("--confirm-owner-release", action="store_true", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "verify":
            result = verify_release_signature()
            print(json.dumps(result, indent=2))
            return 0 if result["signature_valid"] else 1
        if not wt.network_transport_enabled(PINNED_INTENT_DIGEST):   # before secrets/release
            print(json.dumps({"status": "REFUSED_LOCKED", "reason": "order transport lock is "
                              "engaged; lifting it needs the reviewed lock-lift commit and the "
                              "owner's explicit execution authorization",
                              "release_consumed": False, "requests_sent": 0,
                              "execution_release": "NO_GO"}, indent=2))
            return 5
        intent, signature = load_signed_intent()
        data = _data_dir()
        require_pinned_signer(data / "approval_allowed_signers")
        env = lookup.load_local_credentials(str(data.parent / ".env"))
        baseline = EtoroDemoStore(str(data / "etoro_demo.sqlite3")).baseline()
        report = run_pilot(
            intent=intent, release_signature=signature, principal=PRINCIPAL,
            signers_path=str(data / "approval_allowed_signers"), env=env, baseline=baseline,
            baseline_status=recorded_baseline_status(str(data / "sd038-auth-budget.sqlite3")),
            transport_factory=wt.production_transport_factory(env, PINNED_INTENT_DIGEST),
            await_approval=console_approval, paths=OperatorPaths(data / "sd054"))
    except Exception as exc:
        report_path = _data_dir() / "sd054" / "report.json"
        print(json.dumps({"status": "REFUSED_OR_INTERRUPTED",
                          "reason": f"{type(exc).__name__}: {exc}",
                          "see_report": str(report_path) if report_path.is_file() else None,
                          "warning": "if see_report is set, read it: an order may exist",
                          "execution_release": "NO_GO"}, indent=2))
        return 5
    print(json.dumps(report, indent=2, default=str))
    return 0 if report["result"] == "COMPLETE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
