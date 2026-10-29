"""SD-153/R signed dry-run review: local evidence only, never an execution gate."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest

from sidedeck.application.sd153_recovery_review import (
    RECOVERY_REVIEW_NAMESPACE, REVIEW_SCHEMA, review_digest, verify_recovery_review,
)

NOW = datetime(2026, 10, 28, 16, 0, tzinfo=timezone.utc)
PRINCIPAL = "offline-reviewer@sidedeck.test"


class _Verifier:
    def __init__(self, namespace: str = RECOVERY_REVIEW_NAMESPACE) -> None:
        self.namespace = namespace
        self.seen: tuple[str, str, str] | None = None

    def __call__(self, principal: str, digest: str, signature: str) -> bool:
        self.seen = principal, digest, signature
        return principal == PRINCIPAL and signature == f"test-signature:{digest}"


def _manifest() -> dict[str, object]:
    payload: dict[str, object] = {
        "schema": "sidedeck.sd153.offline-recovery-evidence/1",
        "evidence_origin": "LOCAL_OFFLINE_FIXTURE_ONLY",
        "broker_account_verified": False,
        "errors": [],
        "read_preflight": {"planned_get_count": 2},
        "original_offline_baseline_sha256": "a" * 64,
        "policy_digest": "b" * 64,
        "local_order_lineage_sha256": "c" * 64,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=True, allow_nan=False).encode("ascii")
    return {**payload, "manifest_sha256": hashlib.sha256(canonical).hexdigest()}


def _review(manifest: dict[str, object], *, decision: str = "RECONCILED",
            ceiling: int = 2) -> dict[str, object]:
    return {
        "schema": REVIEW_SCHEMA,
        "review_id": "fb22c5b2-b1fa-4b11-a0db-11acaea45544",
        "manifest_sha256": manifest["manifest_sha256"],
        "reviewer_principal": PRINCIPAL,
        "issued_at": NOW.isoformat(),
        "expires_at": (NOW + timedelta(minutes=5)).isoformat(),
        "decision": decision,
        "max_get_requests": ceiling,
    }


def _verify(manifest, review, verifier=None, *, now=NOW):
    active = verifier or _Verifier()
    signature = f"test-signature:{review_digest(review)}"
    return verify_recovery_review(
        manifest=manifest, review_document=review, signature=signature,
        verifier=active, expected_principal=PRINCIPAL, now=now,
    )


def test_sd153_signed_review_reconciles_only_local_dossier_and_cannot_act():
    manifest = _manifest()
    review = _review(manifest)
    verifier = _Verifier()
    result = _verify(manifest, review, verifier)
    assert result["status"] == "RECONCILED"
    assert result["evidence_scope"] == "LOCAL_OFFLINE_DOSSIER_AND_READ_PLAN_ONLY"
    assert result["broker_account_verified"] is False
    assert result["automatic_get_allowed"] is False
    assert result["automatic_post_allowed"] is False
    assert result["database_mutation_allowed"] is False
    assert result["clear_halt_allowed"] is False
    assert verifier.seen == (PRINCIPAL, review_digest(review),
                             f"test-signature:{review_digest(review)}")


def test_sd153_manifest_tamper_or_more_gets_than_signed_ceiling_is_unresolved():
    manifest = _manifest()
    review = _review(manifest, ceiling=1)
    manifest["original_offline_baseline_sha256"] = "d" * 64
    result = _verify(manifest, review)
    assert result["status"] == "UNRESOLVED"
    assert "MANIFEST_DIGEST_INVALID" in result["failure_reasons"]
    assert "REVIEW_GET_CEILING_BELOW_PLAN" in result["failure_reasons"]
    assert result["automatic_get_allowed"] is False


@pytest.mark.parametrize("now", [NOW - timedelta(minutes=1), NOW + timedelta(minutes=6)])
def test_sd153_review_outside_issue_expiry_window_is_unresolved(now):
    manifest = _manifest()
    result = _verify(manifest, _review(manifest), now=now)
    assert result["status"] == "UNRESOLVED"
    assert "REVIEW_TIME_WINDOW_INVALID" in result["failure_reasons"]


def test_sd153_network_grant_signature_namespace_cannot_sign_recovery_review():
    manifest = _manifest()
    network_namespace = _Verifier("sidedeck-network-unlock-grant")
    result = _verify(manifest, _review(manifest), network_namespace)
    assert result["status"] == "UNRESOLVED"
    assert "REVIEW_SIGNATURE_NAMESPACE_INVALID" in result["failure_reasons"]


def test_sd153_bad_signature_and_human_unresolved_decision_fail_closed():
    manifest = _manifest()
    review = _review(manifest)
    verifier = _Verifier()
    result = verify_recovery_review(
        manifest=manifest, review_document=review, signature="forged",
        verifier=verifier, expected_principal=PRINCIPAL, now=NOW,
    )
    assert result["status"] == "UNRESOLVED"
    assert "REVIEW_SIGNATURE_INVALID" in result["failure_reasons"]

    unresolved_review = _review(manifest, decision="UNRESOLVED")
    unresolved = _verify(manifest, unresolved_review)
    assert unresolved["status"] == "UNRESOLVED"
    assert "HUMAN_REVIEW_REQUIRES_FURTHER_EVIDENCE" in unresolved["failure_reasons"]


def test_sd153_human_review_cannot_hide_local_manifest_errors():
    manifest = _manifest()
    manifest["errors"] = ["EXTERNAL_AUDIT_CHECKPOINT_UNVERIFIED"]
    payload = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    manifest["manifest_sha256"] = hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")).hexdigest()
    result = _verify(manifest, _review(manifest))
    assert result["status"] == "UNRESOLVED"
    assert "MANIFEST_HAS_UNRESOLVED_EVIDENCE" in result["failure_reasons"]
