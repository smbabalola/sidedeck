import pytest
from sidedeck.application.p5_preferred_filing_audit import preferred_filing_audit


def fixtures():
    inventory = {"cik": 1818874, "as_of": "2026-10-19",
                 "capital_observations": [
                     {"report_period": "2025-12-31", "filing_date": "2026-02-17",
                      "tag": "PaymentsForRepurchaseOfRedeemablePreferredStock",
                      "value": 323400000, "accession": "0001818874-26-000001"},
                     {"report_period": "2025-12-31", "filing_date": "2026-02-17",
                      "tag": "PreferredStockSharesOutstanding", "value": 0,
                      "accession": "0001818874-26-000001"}]}
    joined = {"ticker": "SOFI", "as_of": "2026-10-19",
              "buffett_ready": False, "broker_execution": "DISABLED",
              "observations": [{"report_period": "2025-12-31", "bvps_preview": 8.2}]}
    return inventory, joined


def test_balance_and_cashflow_not_conflated():
    inventory, joined = fixtures()
    report = preferred_filing_audit(inventory, joined)
    row = report["periods"][0]
    assert len(row["preferred_balance_facts"]) == 1
    assert len(row["preferred_transaction_facts"]) == 1
    assert row["preferred_balance_validated"] is False
    assert row["mapped_to_buffett"] is False
    assert report["approved_periods"] == 0


def test_future_filing_rejected():
    inventory, joined = fixtures()
    inventory["capital_observations"][0]["filing_date"] = "2027-02-17"
    with pytest.raises(ValueError, match="future"):
        preferred_filing_audit(inventory, joined)


def test_approval_elevation_rejected():
    inventory, joined = fixtures()
    joined["buffett_ready"] = True
    with pytest.raises(ValueError, match="approval"):
        preferred_filing_audit(inventory, joined)
