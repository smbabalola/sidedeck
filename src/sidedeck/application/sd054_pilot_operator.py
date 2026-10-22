"""SD-054 supervised eToro Demo pilot operator: one signed release, end to end.

Sequence (every step fails closed; nothing is retried):

1. Verify the owner's SSH signature over the SD-053 intent (namespace
   ``sidedeck-etoro-pilot-release``) and the runtime gates; consume the single-use release.
2. Build the desk with a policy equal to the signed intent and the pilot request budget.
3. Preflight (reads only): baseline MATCHED live, Demo eligibility, fresh realtime ask,
   derived limit; instrument type / currency evidence reported.
4. Print the exact open request and its SD-033 digest; the owner signs it
   (namespace ``sidedeck-paper-approval``). Open, then confirm through lineage lookups.
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
    DemoDeskPolicy, DemoRateBudget, EtoroDemoDesk, EtoroDemoLineage, EtoroDemoTransport,
)
from sidedeck.application.sd045_ssh_approval_verifier import SshSignatureVerifier
from sidedeck.application.sd046_etoro_demo_pilot import (
    PILOT_OPERATOR, UNRESOLVED, EtoroDemoPilot, PilotBudget, PilotTransport,
)
from sidedeck.application.sd048_pilot_release import (
    PILOT_NAMESPACE, PilotIntent, PilotRelease, PilotReleaseStore, ReleaseGates, authorize_pilot,
)
from sidedeck.domain.etoro_demo_books import BaselinePosition

REQUESTER = "sidedeck-pilot-runner"
OPEN_APPROVAL_TTL = timedelta(minutes=5)      # the fresh quote must still be <= 5 min old
CLOSE_APPROVAL_TTL = timedelta(minutes=30)
READY = "READY_FOR_OPEN_APPROVAL"
OPENED = "OPEN_FILLED_AWAITING_CLOSE_APPROVAL"

TransportFactory = Callable[[PilotRelease, str], EtoroDemoTransport]
# (label, digest, scope) -> SSH signature text, or "" to decline.
ApprovalPrompt = Callable[[str, str, str], str]


class OperatorRefused(RuntimeError):
    """Refused before any broker request."""


@dataclass(frozen=True)
class OperatorPaths:
    root: Path

    def __getattr__(self, name: str) -> str:
        if name in ("controls", "lineage", "outbox", "rate", "budget", "releases", "ledger"):
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
    approval_verifier = SshSignatureVerifier(signers_path, principal)
    controls = ApprovalKillSwitch(paths.controls, approval_verifier)
    budget = PilotBudget(paths.budget)
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
    try:
        gates = ReleaseGates.from_runtime(env=env, controls=controls, pilot_budget=budget,
                                          baseline_status=baseline_status,
                                          signers_path=signers_path)
        release = authorize_pilot(intent=intent, signature=release_signature,
                                  principal=principal, verifier=release_verifier, gates=gates,
                                  baseline=baseline, store=store)
        http = transport_factory(release, paths.ledger)
        stores.append(http)
        transport = PilotTransport(http, budget)
        desk = EtoroDemoDesk(
            outbox=outbox, controls=controls, lineage=lineage, transport=transport,
            policy=DemoDeskPolicy(intent.max_notional_usd, frozenset({intent.instrument_id}), 1),
            baseline=baseline, budget=rate, pilot_release=release)
        pilot = EtoroDemoPilot(desk=desk, transport=transport, budget=budget, controls=controls,
                               lineage=lineage, baseline=baseline, scope=intent.scope(),
                               release=release)

        step = pilot.preflight()
        report["steps"].append(step)
        if step["result"] != READY:
            return _finish(report, step["result"], paths)

        request, scope = pilot.open_approval_scope()
        open_id = f"sd054-open-{intent.pilot_id}"
        report["open_request"] = {"instrument_id": request.instrument_id,
                                  "units": str(request.units),
                                  "limit_rate": str(request.limit_rate)}
        signature = await_approval("open", intent_digest(open_id, scope), scope)
        if not _approve(controls, intent_id=open_id, scope=scope, principal=principal,
                        signature=signature, ttl=OPEN_APPROVAL_TTL):
            return _finish(report, "ABORTED_OPEN_NOT_APPROVED", paths)   # nothing written
        step = pilot.open_phase(intent_id=open_id)
        report["steps"].append(step)
        if step["result"] != OPENED:
            return _finish(report, step["result"], paths)

        close_request, close_scope = pilot.close_request(str(uuid.uuid4()))
        close_id = f"sd054-close-{intent.pilot_id}"
        signature = await_approval("close", intent_digest(close_id, close_scope), close_scope)
        if not _approve(controls, intent_id=close_id, scope=close_scope, principal=principal,
                        signature=signature, ttl=CLOSE_APPROVAL_TTL):
            if not controls.is_halted():
                controls.trip(PILOT_OPERATOR, "close not approved; pilot position remains open")
            return _finish(report, UNRESOLVED, paths,
                           reason="close not approved; position remains OPEN")
        step = pilot.close_phase(intent_id=close_id, request=close_request)
        report["steps"].append(step)
        return _finish(report, step["result"], paths)
    finally:
        for item in reversed(stores):
            closer = getattr(item, "close", None)
            if callable(closer):
                closer()


def _finish(report: dict[str, Any], result: str, paths: OperatorPaths,
            **extra: Any) -> dict[str, Any]:
    report.update({"result": result, "finished_at": datetime.now(timezone.utc).isoformat(),
                   **extra})
    paths.report.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
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
PINNED_INTENT_DIGEST = "71e111b3a8806dc9b8e59d96ce1ef6e6a0b64dc2b00363465244acccaad09a62"
PRINCIPAL = "owner@sidedeck"


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
    verifier = SshSignatureVerifier(str(_data_dir() / "approval_allowed_signers"), PRINCIPAL,
                                    namespace=PILOT_NAMESPACE)
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
    path.write_bytes(digest.encode("ascii"))
    print(json.dumps({"approval": label, "scope": scope, "digest": digest,
                      "sign_with": "ssh-keygen -Y sign -f \"$HOME\\.ssh\\sidedeck_approval\" "
                                   f"-n sidedeck-paper-approval \"{path}\""}, indent=2))
    answer = input(f"Sign the {label} digest, then press Enter (type NO to decline): ")
    signature = path.with_name(path.name + ".sig")
    if answer.strip().upper() == "NO" or not signature.is_file():
        return ""
    return signature.read_text(encoding="utf-8")


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
        if not wt.network_transport_enabled():        # before secrets or the release
            print(json.dumps({"status": "REFUSED_LOCKED", "reason": "order transport lock is "
                              "engaged; lifting it needs the reviewed lock-lift commit and the "
                              "owner's explicit execution authorization",
                              "release_consumed": False, "requests_sent": 0,
                              "execution_release": "NO_GO"}, indent=2))
            return 5
        intent, signature = load_signed_intent()
        data = _data_dir()
        env = lookup.load_local_credentials(str(data.parent / ".env"))
        baseline = EtoroDemoStore(str(data / "etoro_demo.sqlite3")).baseline()
        report = run_pilot(
            intent=intent, release_signature=signature, principal=PRINCIPAL,
            signers_path=str(data / "approval_allowed_signers"), env=env, baseline=baseline,
            baseline_status=recorded_baseline_status(str(data / "sd038-auth-budget.sqlite3")),
            transport_factory=wt.production_transport_factory(env),
            await_approval=console_approval, paths=OperatorPaths(data / "sd054"))
    except Exception as exc:
        print(json.dumps({"status": "REFUSED", "reason": f"{type(exc).__name__}: {exc}",
                          "execution_release": "NO_GO"}, indent=2))
        return 5
    print(json.dumps(report, indent=2, default=str))
    return 0 if report["result"] == "COMPLETE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
