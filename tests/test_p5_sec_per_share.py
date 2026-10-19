from sidedeck.application.p5_sec_per_share import reported_per_share
from sidedeck.application.p5_sec_multimetric import preview_multimetric
from sidedeck.application.p5_fundamentals_gate import assess_preview


def fact(tag, start, end, filed, value, accession, unit):
    return tag, unit, {"start": start, "end": end, "filed": filed,
                       "val": value, "form": "10-Q", "accn": accession}


def test_eps_shares_point_in_time_and_restatement():
    specs = [
        fact("EarningsPerShareDiluted", "2025-01-01", "2025-03-31", "2025-05-01", 0.25, "original", "USD/shares"),
        fact("EarningsPerShareDiluted", "2025-01-01", "2025-03-31", "2026-05-01", 9.0, "later", "USD/shares"),
        fact("WeightedAverageNumberOfDilutedSharesOutstanding", "2025-01-01", "2025-03-31", "2025-05-01", 1000, "shares", "shares"),
    ]
    gaap = {}
    for tag, unit, entry in specs:
        gaap.setdefault(tag, {"units": {}})["units"].setdefault(unit, []).append(entry)
    payload = {"facts": {"us-gaap": gaap}}
    result = reported_per_share(payload, "2026-10-19")
    assert len(result["diluted_eps_reported"]) == 1
    assert result["diluted_eps_reported"][0]["value"] == 0.25
    assert result["diluted_eps_reported"][0]["source"]["accession"] == "original"
    assert result["weighted_average_diluted_shares_reported"][0]["value"] == 1000
    assert reported_per_share(payload, "2025-04-01")["diluted_eps_reported"] == []


def test_multimetric_gate_keeps_pe_blocked():
    gaap = {
        "EarningsPerShareDiluted": {"units": {"USD/shares": [
            {"start": "2025-01-01", "end": "2025-03-31", "filed": "2025-05-01",
             "val": 0.25, "form": "10-Q", "accn": "a"}]}},
        "WeightedAverageNumberOfDilutedSharesOutstanding": {"units": {"shares": [
            {"start": "2025-01-01", "end": "2025-03-31", "filed": "2025-05-01",
             "val": 1000, "form": "10-Q", "accn": "a"}]}},
    }
    metrics = preview_multimetric({"facts": {"us-gaap": gaap}}, "2025-05-02")
    report = assess_preview({"as_of": "2025-05-02", "metrics": metrics})
    assert report["diluted_eps_observations"] == 1
    assert report["diluted_shares_observations"] == 1
    assert "price_to_earnings:validated_ttm_eps_and_historical_prices_missing" in report["blockers"]
    assert report["assessment"] == "NO_GO"
    assert report["broker_execution"] == "DISABLED"
