from sidedeck.application.sd152_offline_cross_ledger import summarize_recovery_evidence


def fence():
    return {"schema": "sidedeck.sd152.operator-status/1",
            "execution_release": "ETORO_DEMO_NOT_RELEASED",
            "safe_to_trade": False, "clear_halt_allowed": False,
            "fence_state": "IDLE"}


def manifest():
    return {"schema": "sidedeck.sd153.offline-recovery-evidence/1",
            "evidence_origin": "LOCAL_OFFLINE_FIXTURE_ONLY",
            "execution_release": "ETORO_DEMO_NOT_RELEASED",
            "owner_signature": "NOT_PROVIDED",
            "broker_account_verified": False,
            "status": "NO_RECOVERY_READS_NEEDED",
            "manifest_sha256": "a" * 64, "errors": []}


def test_clean_local_evidence_never_proves_remote_account():
    x = summarize_recovery_evidence(fence(), manifest())
    assert x["status"] == "MANUAL_REVIEW_REQUIRED"
    assert "BROKER_ACCOUNT_UNVERIFIED" in x["reasons"]
    assert not x["automatic_post_allowed"]


def test_missing_manifest_requires_manual_review():
    x = summarize_recovery_evidence(fence(), None)
    assert "RECOVERY_MANIFEST_UNAVAILABLE" in x["reasons"]
    assert not x["clear_halt_allowed"]


def test_unresolved_order_and_worker_are_preserved():
    m = {**manifest(), "status": "UNRESOLVED",
         "errors": ["EXTERNAL_AUDIT_CHECKPOINT_UNVERIFIED"]}
    x = summarize_recovery_evidence({**fence(), "fence_state": "RUNNING"}, m)
    assert "WORKER_FENCE_NOT_IDLE" in x["reasons"]
    assert "RECOVERY_MANIFEST_ERRORS" in x["reasons"]


def test_forged_release_and_broker_authority_fail_closed():
    m = {**manifest(), "execution_release": "RELEASED",
         "broker_account_verified": True}
    x = summarize_recovery_evidence({**fence(), "safe_to_trade": True}, m)
    assert "FENCE_EVIDENCE_INVALID" in x["reasons"]
    assert "BROKER_VERIFICATION_CLAIM_INVALID" in x["reasons"]
    assert x["execution_release"] == "ETORO_DEMO_NOT_RELEASED"
