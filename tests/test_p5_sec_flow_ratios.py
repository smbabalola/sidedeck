from sidedeck.application.p5_sec_flow_ratios import derive_flow_ttm, derive_roe_preview


def fact(start, end, filed, value, form="10-Q", accession="a"):
    return {"start": start, "end": end, "filed": filed, "val": value,
            "form": form, "accn": accession}


def sec(rows):
    return {"facts": {"us-gaap": {
        "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": rows}},
    }}}


def balance(period, filed, value):
    return {"report_period": period, "filing_date": filed, "value": value,
            "source": {"accession": "sec", "unit": "USD", "filed": filed}}


def test_cash_flow_ttm_filing_date_and_source_tag():
    data = sec([
        fact("2024-01-01", "2024-03-31", "2024-05-01", 20),
        fact("2024-01-01", "2024-12-31", "2025-02-01", 100, "10-K"),
        fact("2025-01-01", "2025-03-31", "2025-05-01", 35),
    ])
    rows = derive_flow_ttm(data, "2025-05-02", "NetCashProvidedByUsedInOperatingActivities")
    row = next(x for x in rows if x["report_period"] == "2025-03-31")
    assert row["value"] == 115
    assert all(x["tag"] == "NetCashProvidedByUsedInOperatingActivities" for x in row["components"])
    assert all(x["report_period"] != "2025-03-31" for x in
               derive_flow_ttm(data, "2025-04-01", "NetCashProvidedByUsedInOperatingActivities"))


def test_roe_from_aligned_year_apart_equity():
    income = [{"report_period": "2025-03-31", "filing_date": "2025-05-01",
               "value": 30, "components": [{"accession": "income"}]}]
    balances = [balance("2024-03-31", "2024-05-01", 100),
                balance("2025-03-31", "2025-05-01", 200)]
    rows = derive_roe_preview(income, balances, "2025-05-02")
    assert len(rows) == 1
    assert rows[0]["return_on_equity"] == 0.2
    assert len(rows[0]["components"]) == 3


def test_roe_missing_or_future_filing_fails_closed():
    income = [{"report_period": "2025-03-31", "filing_date": "2025-05-01",
               "value": 30, "components": []}]
    balances = [balance("2024-03-31", "2024-05-01", 100),
                balance("2025-03-31", "2025-06-01", 200)]
    assert derive_roe_preview(income, balances, "2025-05-02") == []
    assert derive_roe_preview(income, balances[:1], "2025-07-01") == []


def test_unknown_flow_tag_rejected():
    import pytest
    with pytest.raises(ValueError):
        derive_flow_ttm({}, "2025-05-01", "InventedProfit")
