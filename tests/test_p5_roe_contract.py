"""Contract test: SEC ROE producer and the fundamentals gate use the same field."""
from sidedeck.application.p5_fundamentals_gate import assess_preview
from sidedeck.application.p5_sec_multimetric import preview_multimetric


def _fact(start, end, filed, amount, form, accession):
    fact = {"end": end, "filed": filed, "val": amount,
            "form": form, "accn": accession}
    if start is not None:
        fact["start"] = start
    return fact


def test_multimetric_roe_is_consumed_by_gate():
    net_income = [
        _fact("2024-01-01", "2024-03-31", "2024-05-01", 20, "10-Q", "ni-q-old"),
        _fact("2024-01-01", "2024-12-31", "2025-02-01", 100, "10-K", "ni-fy"),
        _fact("2025-01-01", "2025-03-31", "2025-05-01", 35, "10-Q", "ni-q-new"),
    ]
    equity = [
        _fact(None, "2024-03-31", "2024-05-01", 100, "10-Q", "eq-old"),
        _fact(None, "2025-03-31", "2025-05-01", 200, "10-Q", "eq-new"),
    ]
    sec = {"facts": {"us-gaap": {
        "NetIncomeLoss": {"units": {"USD": net_income}},
        "StockholdersEquity": {"units": {"USD": equity}},
    }}}
    metrics = preview_multimetric(sec, "2025-05-02")
    assert "return_on_equity_derived" not in metrics
    rows = metrics["return_on_equity_preview"]
    assert len(rows) == 1
    assert rows[0]["report_period"] == "2025-03-31"
    assert rows[0]["return_on_equity"] == 115 / 150
    assert {part["accession"] for part in rows[0]["sources"]} == {
        "ni-q-old", "ni-fy", "ni-q-new", "eq-old", "eq-new",
    }
    output = assess_preview({"as_of": "2025-05-02", "metrics": metrics})
    assert output["roe_preview_records"] == 1
    assert output["assessment"] == "NO_GO"
    assert output["broker_execution"] == "DISABLED"
