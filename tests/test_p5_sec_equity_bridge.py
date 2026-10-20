import pytest
from sidedeck.application.p5_sec_equity_bridge import equity_bridge


def inputs():
    base = {"ticker": "SOFI", "as_of": "2026-10-19", "buffett_ready": False,
            "broker_execution": "DISABLED", "buffett_periods": 1,
            "observations": [{"report_period": "2026-06-30",
                              "equity_source": {"accession": "a1"},
                              "shares_source": {"accession": "a1"},
                              "mapped_to_buffett": False}]}
    raw = {"cik": 1818874, "facts": {"us-gaap": {"StockholdersEquity": {
        "units": {"USD": [{"end": "2026-06-30", "filed": "2026-08-05",
                           "form": "10-Q", "accn": "a1", "val": 100},
                          {"end": "2026-06-30", "filed": "2026-08-05",
                           "form": "10-Q", "accn": "other", "val": 999}]}}}}}
    return base, raw


def test_same_accession_facts_only():
    report = equity_bridge(*inputs())
    facts = report["observations"][0]["matching_capital_facts"]
    assert len(facts) == 1 and facts[0]["value"] == 100
    assert report["approved_periods"] == 0
    assert report["observations"][0]["common_equity_verified"] is False


def test_future_filing_does_not_pass():
    joined, raw = inputs()
    raw["facts"]["us-gaap"]["StockholdersEquity"]["units"]["USD"][0]["filed"] = "2027-01-01"
    assert equity_bridge(joined, raw)["observations"][0]["matching_capital_facts"] == []


def test_source_accession_mismatch_fails():
    joined, raw = inputs()
    joined["observations"][0]["shares_source"]["accession"] = "other"
    with pytest.raises(ValueError, match="accession mismatch"):
        equity_bridge(joined, raw)


def test_mapped_input_fails():
    joined, raw = inputs()
    joined["observations"][0]["mapped_to_buffett"] = True
    with pytest.raises(ValueError, match="mapped"):
        equity_bridge(joined, raw)
