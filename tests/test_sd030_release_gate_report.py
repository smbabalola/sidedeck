from __future__ import annotations

import pytest

from sidedeck.application.sd027_paper_readiness_audit import audit_paper_release_controls
from sidedeck.application.sd029_operator_rehearsal import rehearsal_report
from sidedeck.application.sd030_release_gate_report import build_release_gate_report


def test_release_gate_is_sanitized_and_never_go() -> None:
    report = build_release_gate_report(audit_paper_release_controls(), rehearsal_report())
    assert report["overall_status"] == "NO_GO"
    assert report["release_enabled"] is False
    assert report["paper_order_submission"] == "DISABLED"
    assert report["human_approval"] == "REQUIRED_SEPARATE_OWNER_RELEASE"
    assert "approval_signature" in report["blocking_controls"]
    assert "account_id" not in str(report).lower()
    assert "api_key" not in str(report).lower()


def test_gate_rejects_any_non_no_go_readiness() -> None:
    audit = audit_paper_release_controls()
    audit["overall_status"] = "GO"
    with pytest.raises(ValueError, match="NO_GO"):
        build_release_gate_report(audit, rehearsal_report())
