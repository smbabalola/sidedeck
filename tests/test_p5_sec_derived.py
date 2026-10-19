from sidedeck.application.p5_sec_derived import cash_flow_ttm, roe_from_filed_equity


def fact(start, end, filed, val, form, accn):
    return {"start": start, "end": end, "filed": filed, "val": val,
            "form": form, "accn": accn}


def test_cash_flow_ttm_preserves_correct_source_tag():
    payload = {"facts": {"us-gaap": {"NetCashProvidedByUsedInOperatingActivities": {
        "units": {"USD": [
            fact("2024-01-01", "2024-03-31", "2024-05-01", 20, "10-Q", "q1"),
            fact("2024-01-01", "2024-12-31", "2025-02-01", 100, "10-K", "fy"),
            fact("2025-01-01", "2025-03-31", "2025-05-01", 35, "10-Q", "new"),
        ]}
    }}}}
    results = cash_flow_ttm(payload, "2025-05-02")
    current = next(r for r in results if r["report_period"] == "2025-03-31")
    assert current["value"] == 115
    assert len(current["components"]) == 3
    assert all(s["tag"] == "NetCashProvidedByUsedInOperatingActivities"
               for s in current["components"])


def equity(value, period, filed, accn):
    return {"value": value, "report_period": period, "filing_date": filed,
            "source": {"filed": filed, "accession": accn, "unit": "USD"}}


def test_roe_reconciles_annual_numerator_and_two_equity_snapshots():
    income = [{"report_period": "2025-03-31", "filing_date": "2025-05-01",
               "value": 20, "components": [{"accession": "ni", "tag": "NetIncomeLoss"}]}]
    balance = [
        equity(90, "2024-03-31", "2024-05-01", "old"),
        equity(110, "2025-03-31", "2025-05-01", "new"),
    ]
    result = roe_from_filed_equity(income, balance, "2025-06-01")
    assert len(result) == 1
    assert result[0]["return_on_equity"] == 0.2
    assert len(result[0]["sources"]) == 3


def test_roe_refuses_unpublished_equity():
    income = [{"report_period": "2025-03-31", "filing_date": "2025-05-01",
               "value": 20, "components": [{"accession": "ni"}]}]
    balance = [
        equity(90, "2024-03-31", "2024-05-01", "old"),
        equity(110, "2025-03-31", "2025-07-01", "future"),
    ]
    assert roe_from_filed_equity(income, balance, "2025-06-01") == []


def test_missing_comparison_equity_blocks_roe():
    income = [{"report_period": "2025-03-31", "filing_date": "2025-05-01",
               "value": 20, "components": [{"accession": "ni"}]}]
    assert roe_from_filed_equity(
        income, [equity(110, "2025-03-31", "2025-05-01", "new")], "2025-06-01"
    ) == []
