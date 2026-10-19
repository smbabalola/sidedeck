from sidedeck.application.p5_sec_multimetric import preview_multimetric


def raw(start=None, filed="2025-02-01", end="2024-12-31", value=200, accn="original", form="10-K"):
    data = {"filed": filed, "end": end, "val": value, "accn": accn, "form": form}
    if start:
        data["start"] = start
    return data


def payload():
    return {"facts": {"us-gaap": {
        "NetIncomeLoss": {"units": {"USD": [
            raw(start="2024-01-01", value=100),
        ]}},
        "Assets": {"units": {"USD": [
            raw(value=200, accn="earliest"),
            raw(filed="2026-02-01", value=900, accn="late"),
        ]}},
        "Liabilities": {"units": {"USD": [
            raw(value=70),
        ]}},
        "StockholdersEquity": {"units": {"USD": [
            raw(value=130),
        ]}},
    }}}


def test_multimetric_instant_balance_sheet_is_filing_dated():
    metrics = preview_multimetric(payload(), "2025-12-31")
    assert metrics["assets_instant"][0]["value"] == 200
    assert metrics["assets_instant"][0]["source"]["accession"] == "earliest"
    assert metrics["stockholders_equity_instant"][0]["value"] == 130
    assert metrics["net_income_ttm"][0]["value"] == 100


def test_cutoff_blocks_later_report():
    assert preview_multimetric(payload(), "2025-01-01")["assets_instant"] == []


def test_no_computed_valuation_without_prices():
    metrics = preview_multimetric(payload(), "2025-12-31")
    assert "price_to_earnings_ratio" not in metrics
    assert "return_on_equity" not in metrics
