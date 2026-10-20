"""Synthetic inputs only: these numbers are test fixtures, not SOFI observations."""
import json
from decimal import Decimal

import pytest

from sidedeck.application.p5_buffett_coverage import (
    SNAPSHOT_FIELDS,
    concept_inventory,
    cost_bound,
    coverage_report,
)

PERIODS = ["2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30", "2025-06-30"]
FILED = ["2026-08-06", "2026-05-06", "2026-02-27", "2025-11-05", "2025-08-05"]
URL = "https://www.sec.gov/Archives/edgar/data/1/000000000026000001/"


def _write(tmp_path, extra_by_index=None):
    records = []
    for i, (period, filed) in enumerate(zip(PERIODS, FILED)):
        record = {"report_period": period, "filing_date": filed, "period": "ttm",
                  "source_url": URL, "return_on_equity": 0.05 + i / 100}
        record.update((extra_by_index or {}).get(i, {}))
        records.append(record)
    path = tmp_path / "fundamentals.json"
    path.write_text(json.dumps({"ticker": "TEST", "records": records}), encoding="utf-8")
    return path


def test_snapshot_fields_mirror_pinned_upstream_period_fundamentals():
    assert SNAPSHOT_FIELDS == (
        "market_cap", "price_to_earnings_ratio", "return_on_equity", "gross_margin",
        "operating_margin", "net_margin", "debt_to_equity", "current_ratio",
        "revenue_growth", "earnings_per_share", "book_value_per_share",
        "free_cash_flow_per_share",
    )


def test_roe_only_file_is_counted_honestly_and_fails_coverage_gate(tmp_path):
    report = coverage_report(_write(tmp_path), "TEST", "2026-10-19")
    fields = report["fields"]
    assert fields["return_on_equity"] == {"populated": 5, "eligible_periods": 5,
                                          "newest_period": True}
    assert fields["net_margin"]["populated"] == 0
    assert report["aggregates"]["roe_avg"] == "COMPUTABLE"
    assert report["aggregates"]["market_cap_latest"] == "UNAVAILABLE"
    assert report["aggregates"]["eps_growth_yoy"] == "UNAVAILABLE"
    gaps = report["checklist"]
    assert gaps["moat"]["status"] == "PARTIAL"
    assert gaps["valuation"]["status"] == "NO_EVIDENCE"
    assert gaps["financial_strength"]["status"] == "NO_EVIDENCE"
    assert report["coverage_gate"] == "FAIL"
    assert report["assessment"] == "NO_GO"
    assert report["broker_execution"] == "DISABLED"
    assert report["financial_datasets_required"] is False


def test_future_filings_are_excluded_from_coverage(tmp_path):
    report = coverage_report(_write(tmp_path), "TEST", "2026-05-10")
    assert report["eligible_periods"] == 4
    assert report["newest_report_period"] == "2026-03-31"


def test_fewer_than_four_filed_periods_fails_closed(tmp_path):
    from sidedeck.bridges.filed_fundamentals import FundamentalsDataError
    with pytest.raises(FundamentalsDataError, match="four"):
        coverage_report(_write(tmp_path), "TEST", "2026-03-01")


def test_eps_growth_requires_newest_and_year_ago_positive_eps(tmp_path):
    path = _write(tmp_path, {0: {"earnings_per_share": 0.4},
                             4: {"earnings_per_share": 0.2}})
    report = coverage_report(path, "TEST", "2026-10-19")
    assert report["aggregates"]["eps_growth_yoy"] == "COMPUTABLE"
    path = _write(tmp_path, {0: {"earnings_per_share": 0.4},
                             4: {"earnings_per_share": -0.2}})
    report = coverage_report(path, "TEST", "2026-10-19")
    assert report["aggregates"]["eps_growth_yoy"] == "UNAVAILABLE"


def test_gate_passes_only_when_every_checklist_item_has_newest_evidence(tmp_path):
    newest = {"return_on_equity": 0.1, "net_margin": 0.1, "book_value_per_share": 7.0,
              "debt_to_equity": 0.5, "market_cap": 1e10}
    report = coverage_report(_write(tmp_path, {0: newest}), "TEST", "2026-10-19")
    assert report["coverage_gate"] == "PASS"
    # Passing coverage never approves research or execution by itself.
    assert report["assessment"] == "NO_GO"


def test_concept_inventory_reports_presence_without_asserting_validity():
    facts = {"facts": {"us-gaap": {
        "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [{}, {}, {}]}},
        "RevenuesNetOfInterestExpense": {"units": {"USD": [{}]}},
    }, "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [{}, {}]}}}}}
    inventory = concept_inventory(facts)
    fcf = inventory["free_cash_flow_per_share"]
    assert fcf["candidates"]["us-gaap:NetCashProvidedByUsedInOperatingActivities"] == 3
    assert fcf["candidates"]["us-gaap:PaymentsToAcquireProductiveAssets"] == 0
    assert inventory["market_cap"]["candidates"]["dei:EntityCommonStockSharesOutstanding"] == 2
    assert inventory["market_cap"]["requires_price_evidence"] is True
    assert all(item["validated"] is False for item in inventory.values())


def test_cost_bound_uses_decimal_and_refuses_missing_prices():
    assert cost_bound(1000, 4096, None, None) == "PRICE_NOT_SUPPLIED"
    assert cost_bound(1000, None, Decimal("3"), Decimal("15")) == "OUTPUT_CAP_UNKNOWN"
    assert cost_bound(1_000_000, 1_000_000, Decimal("3"), Decimal("15")) == "18.000000"
    with pytest.raises(ValueError):
        cost_bound(1000, 4096, Decimal("-1"), Decimal("15"))
