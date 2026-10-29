"""SD-112 proposal cannot accidentally become a SWING trade approval."""
from sidedeck.application.sd112_pooled_admission import SCHEMA
from sidedeck.application.sd144_pooled_swing_audit import audit_pooled_swing_candidate


def _report(verdict="PROPOSED_FOR_OWNER_REVIEW"):
    return {
        "schema": SCHEMA,
        "status": "PROPOSAL_ONLY",
        "production_admission_gate": "UNCHANGED (SD-022 + SD-071 per instrument)",
        "strategies": [{
            "strategy": "channel_mr@1",
            "verdict": verdict,
            "holdout": {"status": "SEALED"},
            "pooled_oos": {"trades": 200},
        }],
    }


def test_positive_pooled_proposal_is_not_promoted_to_admission():
    result = audit_pooled_swing_candidate(_report(), "channel_mr@1")
    assert result["status"] == "BLOCKED_EXTERNAL"
    assert "POOLED_EVIDENCE_NOT_PER_INSTRUMENT_ADMISSION" in result["reasons"]
    assert result["broker_execution_allowed"] is False
    assert result["safe_to_trade"] is False


def test_rejected_or_tampered_report_is_denied():
    for report in (
        _report("REJECTED"),
        {**_report(), "status": "ADMITTED"},
        {**_report(), "production_admission_gate": "BYPASSED"},
        {**_report(), "strategies": []},
    ):
        result = audit_pooled_swing_candidate(report, "channel_mr@1")
        assert result["status"] == "BLOCKED_EXTERNAL"
        assert result["broker_execution_allowed"] is False
        assert result["reasons"]
