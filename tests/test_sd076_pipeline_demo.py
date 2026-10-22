from __future__ import annotations

from sidedeck.application.sd076_pipeline_demo import run_demo


def test_demo_is_labelled_synthetic_and_never_eligible_without_admission() -> None:
    summary = run_demo(count=30)
    assert summary["data_basis"] == "SYNTHETIC_FIXTURE"
    assert "not market coverage" in summary["warning"]
    assert summary["scan"]["scanned"] == 30 and summary["scan"]["excluded"] == {}
    # No spread data is supplied, so the DAY track refuses every candidate.
    assert summary["shortlists"]["DAY"]["quant"] == 0
    # Method-only signals without an admitted strategy can never be ELIGIBLE.
    assert "ELIGIBLE" not in summary["swing_decisions"]
    assert summary["execution_permission"] == "NOT_GRANTED_BY_DECISION_ENGINE"
    assert run_demo(count=30)["shortlists"] == summary["shortlists"]   # deterministic
