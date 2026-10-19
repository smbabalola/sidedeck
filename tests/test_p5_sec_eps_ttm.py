from sidedeck.application.p5_sec_eps_ttm import annual_diluted_eps
from sidedeck.application.p5_sec_multimetric import preview_multimetric


def fact(form="10-K", start="2024-01-01", end="2024-12-31", filed="2025-02-01", val=0.4, accn="original"):
    return {"form": form, "start": start, "end": end, "filed": filed, "val": val, "accn": accn}


def payload(records):
    return {"facts": {"us-gaap": {
        "EarningsPerShareDiluted": {"units": {"USD/shares": records}},
    }}}


def test_annual_eps_uses_original_filing_and_no_quarter_addition():
    rows = annual_diluted_eps(payload([
        fact(), fact(filed="2026-02-01", val=9, accn="restated"),
        fact(form="10-Q", start="2025-01-01", end="2025-03-31", filed="2025-05-01", val=0.2),
    ]), "2026-10-19")
    assert len(rows) == 1
    assert rows[0]["eps_ttm"] == 0.4
    assert rows[0]["source"]["accession"] == "original"
    assert rows[0]["method"] == "directly_filed_full_year_eps_no_quarterly_aggregation"


def test_future_annual_eps_unavailable_before_filing():
    assert annual_diluted_eps(payload([fact()]), "2025-01-01") == []


def test_multimetric_includes_annual_eps_but_no_pe():
    metrics = preview_multimetric(payload([fact()]), "2025-05-01")
    assert len(metrics["annual_diluted_eps_ttm"]) == 1
    assert "price_to_earnings_ratio" not in metrics
