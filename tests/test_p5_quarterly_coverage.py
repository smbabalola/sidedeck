import pytest

from sidedeck.application.p5_quarterly_coverage import (
    QuarterlyEvidenceError, quarterly_coverage,
)


def preview():
    date = "2025-03-31"
    filed = "2025-05-01"
    source = {"accession": "000-1", "filed": filed, "unit": "USD"}
    flow = {"report_period": date, "filing_date": filed,
            "value": 20, "components": [source]}
    return {"ticker": "SOFI", "as_of": "2025-05-02",
            "metrics": {"net_income_ttm": [flow],
                        "operating_cash_flow_ttm": [flow.copy()],
                        "return_on_equity_preview": [{
                            "report_period": date, "filing_date": filed,
                            "return_on_equity": 0.1, "sources": [source]}],
                        "stockholders_equity_instant": [{
                            "report_period": date, "filing_date": filed,
                            "value": 100, "source": source}]}}


def test_quarterly_intersection_is_provenance_dated_and_no_go():
    report = quarterly_coverage(preview())
    assert report["complete_period_count"] == 1
    assert report["periods"][0]["available_from"] == "2025-05-01"
    assert report["periods"][0]["metrics"]["net_income_ttm"]["value"] == 20
    assert report["assessment"] == "NO_GO"
    assert report["buffett_ready"] is False
    assert report["broker_execution"] == "DISABLED"


def test_missing_series_removes_coverage_without_inventing_values():
    raw = preview()
    raw["metrics"]["return_on_equity_preview"] = []
    report = quarterly_coverage(raw)
    assert report["complete_period_count"] == 0


def test_future_report_fails_closed():
    raw = preview()
    raw["metrics"]["net_income_ttm"][0]["filing_date"] = "2026-05-01"
    with pytest.raises(QuarterlyEvidenceError):
        quarterly_coverage(raw)


def test_missing_provenance_fails_closed():
    raw = preview()
    raw["metrics"]["net_income_ttm"][0]["components"] = []
    with pytest.raises(QuarterlyEvidenceError):
        quarterly_coverage(raw)
