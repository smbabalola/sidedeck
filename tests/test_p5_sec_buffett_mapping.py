import pytest

from sidedeck.application.p5_sec_buffett_mapping import (
    BuffettMappingUnavailable, map_sec_quarterly_to_buffett,
)


def coverage():
    components = [
        {"accession": "0001818874-26-000054", "filed": "2025-05-01"},
        {"accession": "0001818874-26-000054", "filed": "2025-05-01"},
        {"accession": "0001818874-26-000054", "filed": "2025-05-01"},
    ]
    periods = []
    for month in (3, 6, 9, 12):
        date = f"2025-{month:02d}-28"
        periods.append({"report_period": date, "available_from": "2025-12-31",
                        "metrics": {"return_on_equity_preview": {
                            "filing_date": "2025-12-31", "value": 0.09,
                            "sources": components}}})
    return {"ticker": "SOFI", "as_of": "2026-01-01",
            "complete_period_count": 4, "periods": periods}


def test_roes_mapped_without_inventing_buffett_metrics():
    mapped, audit = map_sec_quarterly_to_buffett(coverage(), 1818874)
    assert len(mapped["records"]) == 4
    assert all(set(row) == {"report_period", "filing_date", "period",
                            "source_url", "return_on_equity"}
               for row in mapped["records"])
    assert mapped["records"][0]["source_url"].startswith("https://www.sec.gov/Archives/")
    assert audit["mapped_periods"] == 4
    assert audit["buffett_ready"] is False
    assert audit["broker_execution"] == "DISABLED"


def test_bad_source_accession_fails_closed():
    raw = coverage()
    raw["periods"][0]["metrics"]["return_on_equity_preview"]["sources"][0]["accession"] = "placeholder"
    with pytest.raises(BuffettMappingUnavailable, match="accession"):
        map_sec_quarterly_to_buffett(raw, 1818874)


def test_insufficient_coverage_fails_closed():
    raw = coverage()
    raw["periods"] = raw["periods"][:3]
    raw["complete_period_count"] = 3
    with pytest.raises(BuffettMappingUnavailable, match="insufficient"):
        map_sec_quarterly_to_buffett(raw, 1818874)


def annual_eps_preview():
    return {"ticker": "SOFI", "metrics": {"annual_diluted_eps_ttm": [
        {"start": "2024-01-01", "report_period": "2024-12-31",
         "filing_date": "2025-02-24", "eps_ttm": 0.39,
         "method": "directly_filed_full_year_eps_no_quarterly_aggregation",
         "source": {"tag": "EarningsPerShareDiluted", "unit": "USD/shares",
                    "accession": "0001818874-25-000099", "filed": "2025-02-24",
                    "start": "2024-01-01", "end": "2024-12-31"}}
    ]}}


def test_directly_filed_annual_eps_added_only_to_matching_year_end():
    raw = coverage()
    raw["periods"][0]["report_period"] = "2024-12-31"
    raw["periods"][0]["available_from"] = "2025-04-01"
    raw["periods"][0]["metrics"]["return_on_equity_preview"]["filing_date"] = "2025-04-01"
    for source in raw["periods"][0]["metrics"]["return_on_equity_preview"]["sources"]:
        source["filed"] = "2025-02-24"
    mapped, audit = map_sec_quarterly_to_buffett(raw, 1818874, annual_eps_preview())
    rows = {row["report_period"]: row for row in mapped["records"]}
    assert rows["2024-12-31"]["earnings_per_share"] == 0.39
    assert all("earnings_per_share" not in row for k, row in rows.items() if k != "2024-12-31")
    assert next(x for x in audit["evidence"] if x["report_period"] == "2024-12-31")["annual_eps_source"]["tag"] == "EarningsPerShareDiluted"
    assert audit["buffett_ready"] is False


def test_reject_bad_eps_provenance():
    preview = annual_eps_preview()
    preview["metrics"]["annual_diluted_eps_ttm"][0]["source"]["filed"] = "2025-03-01"
    with pytest.raises(BuffettMappingUnavailable, match="annual EPS"):
        map_sec_quarterly_to_buffett(coverage(), 1818874, preview)
