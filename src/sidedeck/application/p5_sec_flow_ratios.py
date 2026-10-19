"""Conservative cash-flow TTM reconstruction and filing-aligned ROE preview.

Historical financial metrics remain research-only. Never authorize Buffett or orders.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from sidedeck.application.p5_sec_ttm import derive_ttm_net_income


def _source(row: dict[str, Any], tag: str) -> dict[str, str]:
    return {"accession": row["accn"], "filed": row["filed"].isoformat(),
            "start": row["start"].isoformat(), "end": row["end"].isoformat(),
            "form": row["form"], "tag": tag, "unit": "USD"}


def derive_flow_ttm(payload: dict[str, Any], as_of: str, tag: str) -> list[dict[str, Any]]:
    """Reuse rigorously dated SEC annual/YTD logic for a specified flow tag."""
    if tag not in ("NetCashProvidedByUsedInOperatingActivities", "NetIncomeLoss"):
        raise ValueError("unapproved financial flow tag")
    if tag == "NetIncomeLoss":
        return derive_ttm_net_income(payload, as_of)
    facts = payload.get("facts", {}).get("us-gaap", {})
    substituted = {"facts": {"us-gaap": {"NetIncomeLoss": facts.get(tag, {})}}}
    result = derive_ttm_net_income(substituted, as_of)
    for row in result:
        for component in row["components"]:
            component["tag"] = tag
    return result


def derive_roe_preview(
    net_income_ttm: list[dict[str, Any]],
    equity_balances: list[dict[str, Any]],
    as_of: str,
) -> list[dict[str, Any]]:
    """ROE = TTM net income / arithmetic mean of ending equity and year-ago equity.

    SEC balances must be original, filed observations, with same reporting-day
    month/day a year apart. No interpolation or current-quarter annualisation.
    """
    cutoff = date.fromisoformat(as_of)
    valid_equity: dict[date, dict[str, Any]] = {}
    for row in equity_balances:
        try:
            period = date.fromisoformat(row["report_period"])
            filed = date.fromisoformat(row["filing_date"])
            src = row["source"]
            value = row["value"]
        except (KeyError, ValueError, TypeError):
            continue
        if filed > cutoff or filed < period or src.get("filed") != row["filing_date"]:
            continue
        if not src.get("accession") or src.get("unit") != "USD":
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        current = valid_equity.get(period)
        if current is None or filed < date.fromisoformat(current["filing_date"]):
            valid_equity[period] = row
    results: list[dict[str, Any]] = []
    for income in net_income_ttm:
        try:
            period = date.fromisoformat(income["report_period"])
            filed = date.fromisoformat(income["filing_date"])
            value = income["value"]
        except (KeyError, ValueError, TypeError):
            continue
        if filed > cutoff or not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        prior = next((p for p in valid_equity if
            364 <= (period - p).days <= 366 and (p.month, p.day) == (period.month, period.day)
        ), None)
        if period not in valid_equity or prior is None:
            continue
        latest = valid_equity[period]
        older = valid_equity[prior]
        average = (float(latest["value"]) + float(older["value"])) / 2
        if average <= 0:
            continue
        filing = max(filed, date.fromisoformat(latest["filing_date"]),
                     date.fromisoformat(older["filing_date"]))
        if filing > cutoff:
            continue
        results.append({
            "report_period": period.isoformat(), "filing_date": filing.isoformat(),
            "return_on_equity": float(value) / average,
            "ttm_net_income": value, "average_equity": average,
            "components": income["components"] + [latest["source"], older["source"]],
        })
    return sorted(results, key=lambda row: row["report_period"], reverse=True)
