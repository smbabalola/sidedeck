"""SD-153/R signed, read-only recovery dossier review.

This verifier classifies the integrity of a local offline recovery dossier and
its proposed read plan. It has no broker route, ledger handle, grant issuer,
database writer, or kill-switch interface. ``RECONCILED`` means only that the
named human reviewer signed a consistent local dossier; it never asserts the
external broker account is reconciled.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

RECOVERY_REVIEW_NAMESPACE = "sidedeck-etoro-demo-recovery-review"
REVIEW_SCHEMA = "sidedeck.sd153.signed-recovery-review/1"
MANIFEST_SCHEMA = "sidedeck.sd153.offline-recovery-evidence/1"
MAX_REVIEW_WINDOW = timedelta(minutes=15)
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_REVIEW_FIELDS = {
    "schema", "review_id", "manifest_sha256", "reviewer_principal",
    "issued_at", "expires_at", "decision", "max_get_requests",
}


class RecoveryReviewVerifier(Protocol):
    namespace: str

    def __call__(self, principal: str, digest: str, signature: str) -> bool: ...


def _canonical(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def _manifest_digest(manifest: Mapping[str, Any]) -> str:
    unsigned = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    return hashlib.sha256(_canonical(unsigned)).hexdigest()


def _parse_time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp type")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("timestamp timezone")
    return result.astimezone(timezone.utc)


def review_digest(review_document: Mapping[str, Any]) -> str:
    """Digest an exact review document for the dedicated SSH signature namespace."""
    return hashlib.sha256(_canonical(review_document)).hexdigest()


def verify_recovery_review(
    *, manifest: Mapping[str, Any], review_document: Mapping[str, Any],
    signature: str, verifier: RecoveryReviewVerifier, expected_principal: str,
    now: datetime,
) -> dict[str, Any]:
    """Return a deterministic review outcome; never authorise or mutate anything.

    The signed document binds the entire local manifest hash, one principal,
    expiry, decision, and a maximum of two proposed GETs. A signature cannot
    turn local fixture evidence into broker evidence or clear any HALT.
    """
    failures: list[str] = []
    if now.tzinfo is None or now.utcoffset() is None:
        failures.append("REVIEW_CLOCK_INVALID")
        now_utc = None
    else:
        now_utc = now.astimezone(timezone.utc)

    if not isinstance(manifest, Mapping):
        failures.append("MANIFEST_MALFORMED")
        manifest_data: Mapping[str, Any] = {}
    else:
        manifest_data = manifest
        if manifest.get("schema") != MANIFEST_SCHEMA:
            failures.append("MANIFEST_SCHEMA_INVALID")
        declared = manifest.get("manifest_sha256")
        try:
            actual = _manifest_digest(manifest)
        except (TypeError, ValueError):
            actual = ""
        if not isinstance(declared, str) or not _DIGEST.fullmatch(declared) or declared != actual:
            failures.append("MANIFEST_DIGEST_INVALID")
        if manifest.get("evidence_origin") != "LOCAL_OFFLINE_FIXTURE_ONLY":
            failures.append("MANIFEST_ORIGIN_UNSUPPORTED")
        if manifest.get("broker_account_verified") is not False:
            failures.append("BROKER_EVIDENCE_SCOPE_INVALID")
        manifest_errors = manifest.get("errors")
        if not isinstance(manifest_errors, list) or manifest_errors:
            failures.append("MANIFEST_HAS_UNRESOLVED_EVIDENCE")

    if not isinstance(review_document, Mapping) or set(review_document) != _REVIEW_FIELDS:
        failures.append("REVIEW_DOCUMENT_FIELDS_INVALID")
        review: Mapping[str, Any] = {}
    else:
        review = review_document
        if review.get("schema") != REVIEW_SCHEMA:
            failures.append("REVIEW_SCHEMA_INVALID")
        try:
            review_id = str(uuid.UUID(str(review.get("review_id"))))
            if review_id != review.get("review_id"):
                failures.append("REVIEW_ID_INVALID")
        except (ValueError, TypeError, AttributeError):
            failures.append("REVIEW_ID_INVALID")
        manifest_digest = manifest_data.get("manifest_sha256")
        if review.get("manifest_sha256") != manifest_digest:
            failures.append("REVIEW_MANIFEST_BINDING_INVALID")
        principal = review.get("reviewer_principal")
        if not isinstance(expected_principal, str) or not expected_principal \
                or principal != expected_principal:
            failures.append("REVIEWER_IDENTITY_INVALID")
        if review.get("decision") not in {"RECONCILED", "UNRESOLVED"}:
            failures.append("REVIEW_DECISION_INVALID")
        ceiling = review.get("max_get_requests")
        if type(ceiling) is not int or not 0 <= ceiling <= 2:
            failures.append("REVIEW_GET_CEILING_INVALID")
        else:
            planned = manifest_data.get("read_preflight")
            planned_count = planned.get("planned_get_count") if isinstance(planned, Mapping) else None
            if type(planned_count) is not int or planned_count < 0 or planned_count > ceiling:
                failures.append("REVIEW_GET_CEILING_BELOW_PLAN")
        try:
            issued = _parse_time(review.get("issued_at"))
            expires = _parse_time(review.get("expires_at"))
            if (expires <= issued or expires - issued > MAX_REVIEW_WINDOW
                    or now_utc is None or issued > now_utc + timedelta(seconds=5)
                    or now_utc >= expires):
                failures.append("REVIEW_TIME_WINDOW_INVALID")
        except (TypeError, ValueError, OverflowError):
            failures.append("REVIEW_TIME_WINDOW_INVALID")

    if getattr(verifier, "namespace", None) != RECOVERY_REVIEW_NAMESPACE:
        failures.append("REVIEW_SIGNATURE_NAMESPACE_INVALID")
    else:
        try:
            signed_digest = review_digest(review)
            if not verifier(str(review.get("reviewer_principal", "")),
                            signed_digest, signature):
                failures.append("REVIEW_SIGNATURE_INVALID")
        except (TypeError, ValueError):
            failures.append("REVIEW_SIGNATURE_INVALID")

    decision = review.get("decision")
    status = "RECONCILED" if not failures and decision == "RECONCILED" else "UNRESOLVED"
    if decision == "UNRESOLVED":
        failures.append("HUMAN_REVIEW_REQUIRES_FURTHER_EVIDENCE")
        status = "UNRESOLVED"
    return {
        "schema": "sidedeck.sd153.recovery-review-verification/1",
        "status": status,
        "failure_reasons": sorted(set(failures)),
        "review_sha256": review_digest(review) if review else None,
        "reviewer_principal": review.get("reviewer_principal"),
        "evidence_scope": "LOCAL_OFFLINE_DOSSIER_AND_READ_PLAN_ONLY",
        "broker_account_verified": False,
        "automatic_get_allowed": False,
        "automatic_post_allowed": False,
        "database_mutation_allowed": False,
        "clear_halt_allowed": False,
        "execution_release": "ETORO_DEMO_NOT_RELEASED",
    }
