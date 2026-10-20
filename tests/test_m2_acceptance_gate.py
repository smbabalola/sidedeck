import pytest

from sidedeck.application.m2_acceptance_gate import ResearchEvidence, readiness_report


def case(**changes):
    values = dict(sec_metrics_validated=10, sec_metrics_expected=12,
                  price_history_corrob=False, corporate_actions_verified=False,
                  valuation_basis_verified=False, agents_executed=False,
                  independent_results_accepted=False, cost_cap_authorized=False)
    values.update(changes)
    return ResearchEvidence(**values)


def test_real_msft_known_blockers_are_explicit():
    result = readiness_report(case())
    assert result["m2_research_acceptance"] == "NO_GO"
    assert "FINANCIAL_COVERAGE_INCOMPLETE" in result["blockers"]
    assert "HISTORICAL_CLOSE_UNCORROBORATED" in result["blockers"]
    assert result["paper_order_release"] == "NO_GO"
    assert result["execution_enabled"] is False


def test_even_complete_research_never_unblocks_broker():
    result = readiness_report(case(sec_metrics_validated=12, price_history_corrob=True,
                                   corporate_actions_verified=True, valuation_basis_verified=True,
                                   agents_executed=True, independent_results_accepted=True,
                                   cost_cap_authorized=True))
    assert result["m2_research_acceptance"] == "EVIDENCE_READY_FOR_REVIEW"
    assert result["paper_order_release"] == "NO_GO"
    assert result["broker_execution"] == "DISABLED"


@pytest.mark.parametrize("actual,expected", [(-1, 12), (13, 12), (0, 0)])
def test_metric_counts_fail_closed(actual, expected):
    with pytest.raises(ValueError):
        readiness_report(case(sec_metrics_validated=actual, sec_metrics_expected=expected))
