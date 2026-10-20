import pytest

from sidedeck.application.p5_msft_sec_inventory import assess_msft_companyfacts


def companyfacts():
    return {"cik": 789019, "facts": {"us-gaap": {
        "NetIncomeLoss": {"units": {"USD": [{"val": 1}]}},
        "StockholdersEquity": {"units": {"USD": [{"val": 2}]}},
    }}}


def test_inventory_does_not_claim_coverage():
    result = assess_msft_companyfacts(companyfacts())
    assert result["ticker"] == "MSFT"
    assert result["candidate_fields_with_some_raw_facts"] > 0
    assert result["coverage_gate"] == "NOT_ASSESSED"
    assert result["research_ready"] is False
    assert result["ttm_reconciled"] is False
    assert result["broker_execution"] == "DISABLED"
    assert all(not entry["approved"] for entry in result["candidate_concepts"].values())


@pytest.mark.parametrize("change", [
    lambda x: x.update({"cik": 1818874}),
    lambda x: x.pop("cik"),
    lambda x: x.update({"facts": {}}),
])
def test_fails_on_wrong_identity_or_taxonomy(change):
    facts = companyfacts()
    change(facts)
    with pytest.raises(ValueError):
        assess_msft_companyfacts(facts)
