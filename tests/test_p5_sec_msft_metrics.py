import copy

import pytest

from sidedeck.application.p5_sec_msft_metrics import MSFTMetricsError, reconstruct_msft_metrics


def _flow(values, tag="x", unit="USD"):
    rows = []
    for year, quarters in values.items():
        total = 0
        for i, (end, start) in enumerate(
            (("03-31", "01-01"), ("06-30", "04-01"), ("09-30", "07-01"))
        ):
            total += quarters[i]
            accn = f"0000000001-{year % 100:02d}-{i + 1:06d}"
            filed = {"03": "05", "06": "08", "09": "11"}[end[:2]]
            rows.append(
                {
                    "start": f"{year}-{start}",
                    "end": f"{year}-{end}",
                    "val": total,
                    "accn": accn,
                    "form": "10-Q",
                    "filed": f"{year}-{filed}-15",
                }
            )
            rows.append(
                {
                    "start": f"{year}-{start}",
                    "end": f"{year}-{end}",
                    "val": quarters[i],
                    "accn": accn,
                    "form": "10-Q",
                    "filed": f"{year}-{filed}-15",
                }
            )
        rows.append(
            {
                "start": f"{year}-01-01",
                "end": f"{year}-12-31",
                "val": sum(quarters),
                "accn": f"0000000001-{year % 100:02d}-000009",
                "form": "10-K",
                "filed": f"{year + 1}-02-15",
            }
        )
    return rows


def _instant(values):
    return [
        {
            "end": end,
            "val": value,
            "accn": "0000000001-25-000001",
            "form": "10-K",
            "filed": f"{int(end[:4]) + 1}-02-15",
        }
        for end, value in values.items()
    ]


def _facts():
    flows = {
        "RevenueFromContractWithCustomerExcludingAssessedTax": [100, 110, 120],
        "GrossProfit": [60, 66, 72],
        "OperatingIncomeLoss": [30, 33, 36],
        "NetIncomeLoss": [20, 22, 24],
        "NetCashProvidedByUsedInOperatingActivities": [25, 27, 29],
        "PaymentsToAcquirePropertyPlantAndEquipment": [5, 6, 7],
        "EarningsPerShareDiluted": [1, 1.1, 1.2],
        "WeightedAverageNumberOfDilutedSharesOutstanding": [100, 100, 100],
    }
    gaap = {
        tag: {"units": {"USD": _flow({2024: vals, 2025: vals})}}
        for tag, vals in flows.items()
        if tag not in {"EarningsPerShareDiluted", "WeightedAverageNumberOfDilutedSharesOutstanding"}
    }
    gaap["EarningsPerShareDiluted"] = {
        "units": {
            "USD/shares": _flow(
                {2024: flows["EarningsPerShareDiluted"], 2025: flows["EarningsPerShareDiluted"]}
            )
        }
    }
    gaap["WeightedAverageNumberOfDilutedSharesOutstanding"] = {
        "units": {
            "shares": _flow(
                {
                    2024: flows["WeightedAverageNumberOfDilutedSharesOutstanding"],
                    2025: flows["WeightedAverageNumberOfDilutedSharesOutstanding"],
                }
            )
        }
    }
    for tag, vals in {
        "StockholdersEquity": {"2024-12-31": 400, "2025-12-31": 450},
        "AssetsCurrent": {"2025-12-31": 300},
        "LiabilitiesCurrent": {"2025-12-31": 150},
        "LongTermDebt": {"2025-12-31": 40},
        "LongTermDebtCurrent": {"2025-12-31": 10},
        "CommonStockSharesOutstanding": {"2025-12-31": 100},
    }.items():
        unit = "shares" if tag == "CommonStockSharesOutstanding" else "USD"
        gaap[tag] = {"units": {unit: _instant(vals)}}
    return {"cik": 789019, "facts": {"us-gaap": gaap}}


def test_reconstructs_point_in_time_metrics_and_keeps_valuation_unavailable():
    payload, audit = reconstruct_msft_metrics(_facts(), "2026-03-01")
    latest = payload["records"][0]
    assert latest["report_period"] == "2025-12-31"
    assert audit["latest_validated_metric_count"] >= 4
    assert "market_cap" not in latest and "price_to_earnings_ratio" not in latest
    assert audit["valuation"] == "UNRESOLVED_HISTORICAL_PRICE_AND_SHARE_BASIS"


def test_future_cutoff_excludes_later_periods():
    _, audit = reconstruct_msft_metrics(_facts(), "2025-02-01")
    assert all(row["report_period"] < "2025-01-01" for row in audit["periods"])


def test_missing_capex_never_becomes_zero_or_fcf_per_share():
    facts = _facts()
    del facts["facts"]["us-gaap"]["PaymentsToAcquirePropertyPlantAndEquipment"]
    payload, audit = reconstruct_msft_metrics(facts, "2026-03-01")
    assert "free_cash_flow_per_share" not in payload["records"][0]
    assert audit["periods"][0]["metrics"]["free_cash_flow_per_share"]["status"] == "UNAVAILABLE"


def test_wrong_issuer_and_input_are_rejected_without_mutation():
    facts = _facts()
    before = copy.deepcopy(facts)
    facts["cik"] = 1
    with pytest.raises(MSFTMetricsError):
        reconstruct_msft_metrics(facts, "2026-03-01")
    assert facts == {**before, "cik": 1}
