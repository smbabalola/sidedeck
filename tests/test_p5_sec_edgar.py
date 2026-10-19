import pytest

from sidedeck.application.p5_sec_edgar import extract_annual_facts


def entry(filed="2025-02-01", val=100, form="10-K", start="2024-01-01"):
    return {
        "form": form, "filed": filed, "start": start, "end": "2024-12-31",
        "accn": "0000000000-25-000001", "val": val,
    }


def sample(entries):
    return {
        "facts": {
            "us-gaap": {
                "NetIncomeLoss": {"units": {"USD": entries}},
            }
        }
    }


def test_annual_facts_are_labeled_annual_only():
    rows = extract_annual_facts(sample([entry()]), "2025-12-31")
    assert len(rows) == 1
    assert rows[0]["period"] == "annual"
    assert rows[0]["metrics"]["net_income"]["value"] == 100
    assert rows[0]["metrics"]["net_income"]["accession"]


def test_future_publication_is_not_released_to_historical_view():
    assert extract_annual_facts(sample([entry()]), "2025-01-01") == []


def test_original_filing_precedes_restatement():
    data = sample([entry(val=100), entry(filed="2026-02-01", val=200)])
    records = extract_annual_facts(data, "2026-12-31")
    assert records[0]["metrics"]["net_income"]["value"] == 100


def test_quarterly_record_is_excluded():
    assert extract_annual_facts(sample([entry(form="10-Q")]), "2025-12-31") == []


def test_short_duration_not_annual():
    assert extract_annual_facts(sample([entry(start="2024-10-01")]), "2025-12-31") == []


def test_missing_gaap_facts_is_empty_not_invented():
    assert extract_annual_facts({"facts": {}}, "2025-12-31") == []


def test_invalid_cutoff_fails():
    with pytest.raises(ValueError):
        extract_annual_facts(sample([entry()]), "not-a-date")
