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
