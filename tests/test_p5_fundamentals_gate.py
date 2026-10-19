from sidedeck.application.p5_fundamentals_gate import assess_preview


def item(value, filed="2025-02-01", period="2024-12-31"):
    return {"value": value, "filing_date": filed, "report_period": period,
            "source": {"filed": filed, "accession": "0001", "unit": "USD"}}


def sample():
    return {"as_of": "2025-05-01", "metrics": {
        "assets_instant": [item(100)],
        "liabilities_instant": [item(30)],
        "stockholders_equity_instant": [item(70)],
        "net_income_ttm": [],
    }}


def test_conservative_ratios_with_source_evidence():
    result = assess_preview(sample())
    assert result["assessment"] == "NO_GO"
    assert result["derived_nontrading_ratios"]["liabilities_to_equity"] == 30 / 70
    assert result["derived_nontrading_ratios"]["equity_to_assets"] == 0.7
    assert result["buffett_ready"] is False


def test_future_filing_is_rejected():
    data = sample()
    data["metrics"]["assets_instant"] = [item(100, filed="2025-06-01")]
    result = assess_preview(data)
    assert "assets_instant:missing_filed_evidence" in result["blockers"]


def test_mismatched_accounting_period_fails_closed():
    data = sample()
    data["metrics"]["liabilities_instant"] = [item(30, period="2023-12-31")]
    result = assess_preview(data)
    assert "balance_sheet:period_mismatch" in result["blockers"]
    assert result["derived_nontrading_ratios"] == {}


def test_bad_balance_sheet_identity_fails_closed():
    data = sample()
    data["metrics"]["stockholders_equity_instant"] = [item(60)]
    result = assess_preview(data)
    assert "balance_sheet:accounting_identity_mismatch" in result["blockers"]
    assert result["derived_nontrading_ratios"] == {}
