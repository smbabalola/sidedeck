"""SD-058 one-request, read-only eToro Demo eligibility diagnostic.

This is intentionally separate from the supervised order pilot. It has no order
transport, no pilot-release dependency and no caller-selected ledger. Production
execution is owner-operated only; tests inject a fake opener and never use the
network.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from sidedeck.application.sd042_etoro_credential_roles import monitoring_credentials
from sidedeck.application.sd045_ssh_approval_verifier import SshSignatureVerifier
from sidedeck.application.sd050_msft_instrument_lookup import DATA_DIR, load_local_credentials
from sidedeck.application.sd058_forensic_audit import PreflightAudit, summarize_schema
from sidedeck.domain.etoro_demo_orders import DEMO_ELIGIBILITY_PATH, response_shape_issues

DIAGNOSTIC_NAMESPACE = "sidedeck-etoro-eligibility-diagnostic"
PRINCIPAL = "owner@sidedeck"
INSTRUMENT_ID = 1004
REQUEST_BODY = {"instrumentIds": [INSTRUMENT_ID], "currency": "USD"}
HOST = "https://public-api.etoro.com"
MAX_WINDOW = timedelta(minutes=30)
MAX_RESPONSE_BYTES = 1_000_000
TIMEOUT_SECONDS = 15.0
PINNED_SIGNER_KEY_SHA256 = "600a7f7e6597cfa2f87b1f3f9891de224c4e2a18b9d534da62888158ebbae0f3"


class DiagnosticRefused(PermissionError):
    """A diagnostic gate failed before an authenticated request was permitted."""


class DiagnosticTransportError(RuntimeError):
    """The single diagnostic read failed; the allowance remains consumed."""


class Opener(Protocol):
    def open(self, request: Request, timeout: float) -> Any: ...


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args: Any) -> None:
        raise DiagnosticTransportError("REDIRECT_REFUSED")


@dataclass(frozen=True)
class DiagnosticIntent:
    intent_id: str
    not_before: datetime
    expires_at: datetime
    broker: str = "etoro-demo"
    environment: str = "DEMO"
    instrument_id: int = INSTRUMENT_ID
    endpoint: str = DEMO_ELIGIBILITY_PATH
    currency: str = "USD"
    max_requests: int = 1
    max_writes: int = 0

    def canonical(self) -> bytes:
        doc = {
            "broker": self.broker, "currency": self.currency,
            "endpoint": self.endpoint, "environment": self.environment,
            "expires_at": _utc(self.expires_at).isoformat(), "instrument_id": self.instrument_id,
            "intent_id": self.intent_id, "max_requests": self.max_requests,
            "max_writes": self.max_writes, "not_before": _utc(self.not_before).isoformat(),
            "request_body": REQUEST_BODY, "schema": "sidedeck-sd058-diagnostic/1",
        }
        return json.dumps(doc, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def digest(self) -> str:
        return hashlib.sha256(self.canonical()).hexdigest()


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise DiagnosticRefused("diagnostic times must be timezone-aware")
    return value.astimezone(UTC)


def _fixed_root() -> Path:
    return (DATA_DIR / "sd058-diagnostic").resolve()


def fixed_paths() -> dict[str, Path]:
    root = _fixed_root()
    return {"root": root, "intent": root / "intent.json", "signature": root / "intent.digest.sig",
            "digest": root / "intent.digest", "ledger": root / "request-ledger.sqlite3",
            "audit": root / "audit.sqlite3"}


def prepare_intent(*, minutes: int = 30, now: datetime | None = None,
                   intent_id: str | None = None) -> tuple[DiagnosticIntent, Path]:
    if type(minutes) is not int or not 1 <= minutes <= 30:
        raise DiagnosticRefused("diagnostic window must be between 1 and 30 minutes")
    start = _utc(now or datetime.now(UTC))
    intent = DiagnosticIntent(intent_id or str(uuid.uuid4()), start, start + timedelta(minutes=minutes))
    if str(uuid.UUID(intent.intent_id)) != intent.intent_id:
        raise DiagnosticRefused("intent_id must be a canonical UUID")
    paths = fixed_paths()
    paths["root"].mkdir(parents=True, exist_ok=True)
    paths["intent"].write_bytes(intent.canonical())
    # Sign the exact 64-byte digest, matching the supervised pilot workflow.
    # A trailing newline would change the signed message and make verification
    # dependent on the shell/file transport rather than canonical bytes.
    paths["digest"].write_text(intent.digest(), encoding="ascii", newline="")
    paths["signature"].unlink(missing_ok=True)
    return intent, paths["digest"]


def _load_intent(path: Path) -> DiagnosticIntent:
    if path.is_symlink() or not path.is_file():
        raise DiagnosticRefused("diagnostic intent is missing or symlinked")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        intent = DiagnosticIntent(
            intent_id=str(doc["intent_id"]),
            not_before=datetime.fromisoformat(doc["not_before"]),
            expires_at=datetime.fromisoformat(doc["expires_at"]),
            broker=doc["broker"], environment=doc["environment"],
            instrument_id=doc["instrument_id"], endpoint=doc["endpoint"],
            currency=doc["currency"], max_requests=doc["max_requests"],
            max_writes=doc["max_writes"],
        )
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise DiagnosticRefused("diagnostic intent is malformed") from exc
    if intent.canonical() != path.read_bytes():
        raise DiagnosticRefused("diagnostic intent canonical bytes changed")
    _validate_intent(intent)
    return intent


def _validate_intent(intent: DiagnosticIntent, now: datetime | None = None) -> None:
    moment = _utc(now or datetime.now(UTC))
    try:
        if str(uuid.UUID(intent.intent_id)) != intent.intent_id:
            raise ValueError
    except ValueError:
        raise DiagnosticRefused("intent_id must be a canonical UUID") from None
    if (intent.broker, intent.environment, intent.instrument_id, intent.endpoint,
            intent.currency, intent.max_requests, intent.max_writes) != (
                "etoro-demo", "DEMO", INSTRUMENT_ID, DEMO_ELIGIBILITY_PATH, "USD", 1, 0):
        raise DiagnosticRefused("diagnostic scope is not the fixed MSFT eligibility request")
    start, end = _utc(intent.not_before), _utc(intent.expires_at)
    if not start < end or end - start > MAX_WINDOW:
        raise DiagnosticRefused("diagnostic window must be positive and at most 30 minutes")
    if not start <= moment < end:
        raise DiagnosticRefused("diagnostic authorization is outside its signed window")


def _require_pinned_signer(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise DiagnosticRefused("pinned owner signer file is missing")
    lines = [line.split() for line in path.read_text(encoding="utf-8").splitlines()
             if line.strip() and not line.lstrip().startswith("#")]
    if (len(lines) != 1 or len(lines[0]) < 3 or lines[0][0] != PRINCIPAL
            or lines[0][1] != "ssh-ed25519"
            or hashlib.sha256(lines[0][2].encode("ascii")).hexdigest()
            != PINNED_SIGNER_KEY_SHA256):
        raise DiagnosticRefused("allowed_signers does not hold exactly the pinned owner key")


class DiagnosticLedger:
    def __init__(self, path: Path) -> None:
        target = path.resolve()
        if target.is_symlink() or target.name != "request-ledger.sqlite3":
            raise DiagnosticRefused("diagnostic ledger path is not fixed")
        target.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(target), isolation_level=None)
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.execute("CREATE TABLE IF NOT EXISTS sd058_diagnostic_requests ("
                         "digest TEXT PRIMARY KEY, intent_id TEXT NOT NULL, reserved_at TEXT NOT NULL, "
                         "outcome TEXT NOT NULL)")

    def reserve(self, intent: DiagnosticIntent, now: datetime) -> None:
        self._db.execute("BEGIN IMMEDIATE")
        try:
            if self._db.execute("SELECT 1 FROM sd058_diagnostic_requests WHERE digest=?",
                                (intent.digest(),)).fetchone():
                raise DiagnosticRefused("diagnostic authorization has already been used")
            self._db.execute("INSERT INTO sd058_diagnostic_requests VALUES (?,?,?,?)",
                             (intent.digest(), intent.intent_id, _utc(now).isoformat(), "RESERVED"))
            self._db.execute("COMMIT")
        except BaseException:
            if self._db.in_transaction:
                self._db.execute("ROLLBACK")
            raise

    def outcome(self, digest: str, value: str) -> None:
        if value not in {"RESPONSE_CAPTURED", "FAILED", "UNCERTAIN"}:
            raise ValueError("invalid diagnostic outcome")
        self._db.execute("UPDATE sd058_diagnostic_requests SET outcome=? WHERE digest=?",
                         (value, digest))

    def close(self) -> None:
        self._db.close()


def _sanitized_report(*, intent: DiagnosticIntent, outcome: str, status: int | None,
                      payload: Any, error: BaseException | None = None) -> dict[str, Any]:
    report: dict[str, Any] = {"schema": "sidedeck-sd058-diagnostic-report/1",
                              "intent_digest": intent.digest(), "outcome": outcome,
                              "http_status": status, "response_schema": summarize_schema(payload),
                              "parser_shape_issues": list(response_shape_issues("eligibility", payload))
                              if isinstance(payload, dict) else []}
    if error is not None:
        report["error_classification"] = type(error).__name__
        report["error_detail"] = str(error)[:300]
    return report


def run_diagnostic(*, intent: DiagnosticIntent, signature: str, env: dict[str, str],
                   allowed_signers: Path, opener: Opener | None = None,
                   now: datetime | None = None) -> dict[str, Any]:
    """Run exactly one diagnostic read after all offline gates pass."""
    moment = _utc(now or datetime.now(UTC))
    _validate_intent(intent, moment)
    _require_pinned_signer(allowed_signers)
    verifier = SshSignatureVerifier(str(allowed_signers), PRINCIPAL,
                                    namespace=DIAGNOSTIC_NAMESPACE)
    if not verifier(PRINCIPAL, intent.digest(), signature):
        raise DiagnosticRefused("owner signature does not verify for this exact diagnostic")
    api_key, user_key = monitoring_credentials(env)
    paths = fixed_paths()
    ledger = DiagnosticLedger(paths["ledger"])
    audit = PreflightAudit(paths["audit"], intent.digest())
    try:
        # Prove the audit path is writable before reserving the allowance or opening a socket.
        audit.record(request_type="authorization", budget={"eligibility": 0},
                     outcome="AUTHORIZED_NOT_SENT")
        ledger.reserve(intent, moment)
        active = opener or build_opener(ProxyHandler({}), _NoRedirect())
        request = Request(HOST + DEMO_ELIGIBILITY_PATH,
                          data=json.dumps(REQUEST_BODY, separators=(",", ":"),
                                          sort_keys=True).encode("utf-8"), method="POST",
                          headers={"x-api-key": api_key, "x-user-key": user_key,
                                   "User-Agent": "SideDeck/0.1 (SD-058 diagnostic)",
                                   "Accept": "application/json", "Content-Type": "application/json",
                                   "x-request-id": str(uuid.uuid4())})
        status: int | None = None
        payload: Any = None
        try:
            response = active.open(request, timeout=TIMEOUT_SECONDS)
            status = int(response.status)
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if status != 200 or len(raw) > MAX_RESPONSE_BYTES:
                raise DiagnosticTransportError("UNEXPECTED_RESPONSE")
            payload = json.loads(raw)
            audit.record(request_type="eligibility", budget={"eligibility": 1},
                         outcome="RESPONSE_CAPTURED", payload=payload)
            ledger.outcome(intent.digest(), "RESPONSE_CAPTURED")
            return _sanitized_report(intent=intent, outcome="RESPONSE_CAPTURED", status=status,
                                     payload=payload)
        except HTTPError as exc:
            status = int(exc.code)
            error = DiagnosticTransportError("HTTP_ERROR")
        except Exception as exc:
            error = exc if isinstance(exc, DiagnosticTransportError) else DiagnosticTransportError(
                "READ_FAILED")
        audit.record(request_type="eligibility", budget={"eligibility": 1}, outcome="FAILED",
                     payload=payload, error=error)
        ledger.outcome(intent.digest(), "UNCERTAIN" if isinstance(error, DiagnosticTransportError)
                       else "FAILED")
        return _sanitized_report(intent=intent, outcome="DIAGNOSTIC_ABORTED", status=status,
                                 payload=payload, error=error)
    finally:
        audit.close()
        ledger.close()


def main(argv: list[str] | None = None) -> int:
    import argparse

    paths = fixed_paths()
    parser = argparse.ArgumentParser(description="SD-058 one-request Demo eligibility diagnostic")
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--minutes", type=int, default=30)
    commands.add_parser("run")
    args = parser.parse_args(argv)
    if args.command == "prepare":
        intent, digest_path = prepare_intent(minutes=args.minutes)
        print(json.dumps({"status": "PREPARED_NOT_AUTHORIZED", "digest": intent.digest(),
                          "digest_file": str(digest_path), "namespace": DIAGNOSTIC_NAMESPACE,
                          "signing": "ssh-keygen -Y sign -f <OWNER_PRIVATE_KEY> -n "
                                     f"{DIAGNOSTIC_NAMESPACE} <digest-file>"}, indent=2))
        return 0
    intent = _load_intent(paths["intent"])
    signature = paths["signature"].read_text(encoding="ascii")
    env = load_local_credentials(str(DATA_DIR.parent / ".env"))
    result = run_diagnostic(intent=intent, signature=signature, env=env,
                            allowed_signers=DATA_DIR / "approval_allowed_signers")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["outcome"] == "RESPONSE_CAPTURED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
