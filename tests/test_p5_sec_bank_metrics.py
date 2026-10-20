"""Synthetic SEC facts only. These numbers are fixtures, not SOFI observations."""
import copy
import json
import tempfile
from pathlib import Path

import pytest

from sidedeck.application.p5_sec_bank_metrics import (
    BankMetricsError,
    discrete_quarters,
    reconstruct_bank_metrics,
)
from sidedeck.bridges.filed_fundamentals import verified_fundamentals

FILED = {"Q1": "-05-06", "Q2": "-08-07", "Q3": "-11-06"}
ENDS = {"Q1": "-03-31", "Q2": "-06-30", "Q3": "-09-30"}
STARTS = {"Q1": "-01-01", "Q2": "-04-01", "Q3": "-07-01"}
AS_OF = "2026-10-19"


def _accn(year: int, n: int) -> str:
    return f"0000000001-{year % 100:02d}-{n:06d}"


def _flow(quarterly: dict[int, list[int]], with_three_month: bool = True) -> list[dict]:
    """10-Q 3-month + YTD facts and 10-K annual facts for each calendar year."""
    rows = []
    for year, values in quarterly.items():
        ytd = 0
        for i, q in enumerate(("Q1", "Q2", "Q3")):
            if i >= len(values):
                break
            ytd += values[i]
            filed = f"{year}{FILED[q]}"
            accn = _accn(year, i + 1)
            rows.append({"start": f"{year}-01-01", "end": f"{year}{ENDS[q]}", "val": ytd,
                         "accn": accn, "form": "10-Q", "filed": filed})
            if with_three_month and q != "Q1":
                rows.append({"start": f"{year}{STARTS[q]}", "end": f"{year}{ENDS[q]}",
                             "val": values[i], "accn": accn, "form": "10-Q", "filed": filed})
        if len(values) == 4:
            rows.append({"start": f"{year}-01-01", "end": f"{year}-12-31", "val": sum(values),
                         "accn": _accn(year + 1, 9), "form": "10-K",
                         "filed": f"{year + 1}-02-20"})
    return rows


def _instant(values: dict[str, int]) -> list[dict]:
    rows = []
    for end, val in values.items():
        year = int(end[:4])
        quarter = {"-03-31": "Q1", "-06-30": "Q2", "-09-30": "Q3"}.get(end[4:])
        filed = f"{year}{FILED[quarter]}" if quarter else f"{year + 1}-02-20"
        form = "10-Q" if quarter else "10-K"
        rows.append({"end": end, "val": val, "accn": _accn(year, 7), "form": form,
                     "filed": filed})
    return rows


def _facts(extra=None):
    gaap = {
        "RevenuesNetOfInterestExpense": {"units": {"USD": _flow(
            {2024: [90, 90, 90, 90], 2025: [100, 100, 100, 100], 2026: [110, 120]})}},
        "NetIncomeLoss": {"units": {"USD": _flow(
            {2024: [9, 9, 9, 9], 2025: [10, 10, 10, 10], 2026: [11, 12]})}},
        "DebtLongtermAndShorttermCombinedAmount": {"units": {"USD": _instant(
            {"2026-06-30": 300, "2026-03-31": 280, "2025-12-31": 250})}},
        "StockholdersEquity": {"units": {"USD": _instant(
            {"2026-06-30": 1000, "2026-03-31": 980, "2025-12-31": 960})}},
        "Deposits": {"units": {"USD": _instant({"2026-06-30": 5000})}},
        "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": _flow(
            {2025: [-50, -60, -70, -80], 2026: [-90, -100]}, with_three_month=False)}},
        "PaymentsToAcquireProductiveAssets": {"units": {"USD": _flow(
            {2025: [5, 5, 5, 5], 2026: [6, 6]}, with_three_month=False)}},
    }
    gaap.update(extra or {})
    return {"facts": {"us-gaap": gaap}}


URL = "https://www.sec.gov/Archives/edgar/data/1/000000000126000001/"


def _base():
    periods = [("2026-06-30", "2026-08-07"), ("2026-03-31", "2026-05-06"),
               ("2025-12-31", "2026-02-20"), ("2025-09-30", "2025-11-06"),
               ("2025-06-30", "2025-08-07")]
    return {"ticker": "TEST", "records": [
        {"report_period": p, "filing_date": f, "period": "ttm", "source_url": URL,
         "return_on_equity": 0.05} for p, f in periods]}


def _metric(audit, period, name):
    row = next(r for r in audit["periods"] if r["report_period"] == period)
    return row["metrics"][name]


def _validated(payload):
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "input.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return verified_fundamentals(path, "TEST", AS_OF)


def test_ttm_revenue_reconciles_against_independent_three_month_facts():
    _, audit = reconstruct_bank_metrics(_facts(), _base(), AS_OF, cik=1)
    margin = _metric(audit, "2026-06-30", "net_margin")
    assert margin["value"] == "0.1"  # (40 + 23 - 20) / (400 + 230 - 200)
    assert margin["included"] is True
    assert margin["definition"] == "ttm_net_income_over_ttm_total_net_revenue"
    revenue = margin["reconciliation"]["revenue_ttm"]
    assert revenue["status"] == "RECONCILED"
    assert revenue["ttm"] == "430" and revenue["quarter_sum"] == "430"
    assert revenue["independent_quarters"] == 2
    assert all(c["accession"] for c in margin["components"])
    growth = _metric(audit, "2026-06-30", "revenue_growth")
    assert growth["value"] == "0.131579"  # 430 / 380 - 1
    assert growth["definition"] == "ttm_total_net_revenue_year_over_year"
    assert growth["included"] is True


def test_mismatched_three_month_fact_excludes_dependent_metrics():
    facts = _facts()
    for row in facts["facts"]["us-gaap"]["RevenuesNetOfInterestExpense"]["units"]["USD"]:
        if row["start"] == "2026-04-01":
            row["val"] = 125
    payload, audit = reconstruct_bank_metrics(facts, _base(), AS_OF, cik=1)
    margin = _metric(audit, "2026-06-30", "net_margin")
    assert margin["reconciliation"]["revenue_ttm"]["status"] == "MISMATCH"
    assert margin["included"] is False
    newest = payload["records"][0]
    assert newest["report_period"] == "2026-06-30"
    assert "net_margin" not in newest and "revenue_growth" not in newest


def test_cash_flow_quarters_without_three_month_facts_are_arithmetic_only():
    quarters = discrete_quarters(_facts(), AS_OF, "NetCashProvidedByUsedInOperatingActivities")
    assert quarters["2026-06-30"]["method"] == "YTD_DIFFERENCE"
    assert quarters["2025-12-31"]["method"] == "ANNUAL_LESS_NINE_MONTHS"
    assert quarters["2026-03-31"]["method"] == "FIRST_QUARTER_YTD"
    assert quarters["2026-06-30"]["value"] == -100


def test_output_passes_upstream_input_validator():
    payload, _ = reconstruct_bank_metrics(_facts(), _base(), AS_OF, cik=1)
    newest = _validated(payload)[0]
    assert newest["net_margin"] == pytest.approx(0.1)
    assert newest["filing_date"] == "2026-08-07"
    assert set(newest) <= {"ticker", "period", "report_period", "filing_date",
                           "return_on_equity", "net_margin", "revenue_growth",
                           "earnings_per_share"}


def test_future_filings_are_not_used():
    _, audit = reconstruct_bank_metrics(_facts(), _base(), "2026-08-01", cik=1)
    assert all(r["report_period"] != "2026-06-30" for r in audit["periods"])


def test_debt_to_equity_is_labelled_and_excluded_without_owner_approval():
    payload, audit = reconstruct_bank_metrics(_facts(), _base(), AS_OF, cik=1)
    de = _metric(audit, "2026-06-30", "debt_to_equity")
    assert de["definition"] == "borrowings_excluding_deposits"
    assert de["value"] == "0.3"
    assert de["context"]["deposits"] == 5000
    assert de["included"] is False
    assert de["status"] == "DEFINITION_APPROVAL_REQUIRED"
    assert "debt_to_equity" not in payload["records"][0]


def test_debt_to_equity_included_only_with_explicit_definition_approval():
    payload, audit = reconstruct_bank_metrics(
        _facts(), _base(), AS_OF, cik=1,
        approved_definitions={"debt_to_equity:borrowings_excluding_deposits"},
    )
    assert payload["records"][0]["debt_to_equity"] == pytest.approx(0.3)
    assert _metric(audit, "2026-06-30", "debt_to_equity")["status"] == "OWNER_APPROVED_DEFINITION"


def test_unknown_definition_approval_is_refused():
    with pytest.raises(BankMetricsError, match="definition"):
        reconstruct_bank_metrics(_facts(), _base(), AS_OF, cik=1,
                                 approved_definitions={"debt_to_equity:total_liabilities"})


def test_fcf_flagged_not_meaningful_when_loan_originations_are_operating():
    extra = {"PaymentsForOriginationAndPurchasesOfLoansHeldForSale":
             {"units": {"USD": [{}]}}}
    payload, audit = reconstruct_bank_metrics(_facts(extra=extra), _base(), AS_OF, cik=1)
    fcf = _metric(audit, "2026-06-30", "free_cash_flow")
    # OCF TTM (-260 - 190 + 110) less capex TTM (20 + 12 - 10).
    assert fcf["value"] == "-362"
    assert fcf["status"] == "NOT_MEANINGFUL_FOR_LENDER"
    assert fcf["included"] is False
    assert audit["field_policy"]["free_cash_flow_per_share"]["status"] == "NOT_MEANINGFUL"
    assert all("free_cash_flow_per_share" not in r for r in payload["records"])


def test_fcf_without_origination_evidence_still_needs_review():
    _, audit = reconstruct_bank_metrics(_facts(), _base(), AS_OF, cik=1)
    fcf = _metric(audit, "2026-06-30", "free_cash_flow")
    assert fcf["status"] == "REVIEW_REQUIRED"
    assert fcf["included"] is False


def test_not_applicable_fields_are_recorded_not_forced():
    payload, audit = reconstruct_bank_metrics(_facts(), _base(), AS_OF, cik=1)
    policy = audit["field_policy"]
    for name in ("gross_margin", "operating_margin", "current_ratio"):
        assert policy[name]["status"] == "NOT_APPLICABLE"
        assert policy[name]["reason"]
        assert all(name not in r for r in payload["records"])
    assert policy["book_value_per_share"]["status"] == "EXCLUDED_PENDING_APPROVAL"
    assert audit["assessment"] == "NO_GO"
    assert audit["broker_execution"] == "DISABLED"


@pytest.mark.parametrize("field", ["book_value_per_share", "gross_margin",
                                   "free_cash_flow_per_share"])
def test_base_input_carrying_excluded_fields_is_refused(field):
    base = _base()
    base["records"][0][field] = 1.0
    with pytest.raises(BankMetricsError, match="excluded"):
        reconstruct_bank_metrics(_facts(), base, AS_OF, cik=1)


def test_inputs_are_not_mutated():
    facts, base = _facts(), _base()
    before = (copy.deepcopy(facts), copy.deepcopy(base))
    reconstruct_bank_metrics(facts, base, AS_OF, cik=1)
    assert (facts, base) == before
