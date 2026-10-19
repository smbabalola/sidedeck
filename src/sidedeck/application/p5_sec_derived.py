"""Conservative SEC cash-flow TTM and filed-equity ROE research calculations.

Research preview only. No trade or Buffett-ready decisions.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from sidedeck.application.p5_sec_ttm import derive_ttm_net_income


class CalculationUnavailable(ValueError):
    pass


def cash_flow_ttm(payload: dict[str, Any], as_of: str) -> list[dict[str, Any]]:
    """Reuse the tested YTD/annual reconstruction on the operating cash-flow tag."""
    facts = payload.get("facts", {}).get("us-gaap", {})
    if not isinstance(facts, dict):
        raise CalculationUnavailable("missing US-GAAP facts")
    cash = facts.get("NetCashProvidedByUsedInOperatingActivities")
    if not isinstance(cash, dict):
        return []
    # Existing provenance-preserving TTM conversion expects NetIncomeLoss;
    # adapt the XBRL tag, then restore the true tag in source evidence.
    adapted = {"facts": {"us-gaap": {"NetIncomeLoss": cash}}}
    output = derive_ttm_net_income(adapted, as_of)
    for record in output:
        for source in record["components"]:
            source["tag"] = "NetCashProvidedByUsedInOperatingActivities"
    return output


def roe_from_filed_equity(
    net_income_ttm: list[dict[str, Any]],
    equity_observations: list[dict[str, Any]],
    as_of: str,
) -> list[dict[str, Any]]:
    """TTM NI divided by average filed equity at matching year-apart dates.

    All numerator components and both denominators must be public as-of
    the *resulting availability date*, not merely the global evaluation cutoff.
    """
    cutoff = date.fromisoformat(as_of)
    by_period: dict[str, dict[str, Any]] = {}
    for row in equity_observations:
        if not isinstance(row, dict) or not isinstance(row.get("source"), dict):
            continue
        try:
            period = date.fromisoformat(row["report_period"])
            filed = date.fromisoformat(row["filing_date"])
        except (TypeError, KeyError, ValueError):
            continue
        value = row.get("value")
        source = row["source"]
        if not (period <= filed <= cutoff and isinstance(value, (int, float))
                and not isinstance(value, bool) and value > 0
                and source.get("filed") == row["filing_date"]
                and source.get("unit") == "USD" and source.get("accession")):
            continue
        prior = by_period.get(row["report_period"])
        if prior is None or row["filing_date"] < prior["filing_date"]:
            by_period[row["report_period"]] = row

    output: list[dict[str, Any]] = []
    for row in net_income_ttm:
        try:
            end = date.fromisoformat(row["report_period"])
            filed = date.fromisoformat(row["filing_date"])
        except (KeyError, ValueError, TypeError):
            continue
        if filed > cutoff or end > filed or not row.get("components"):
            continue
        current = by_period.get(end.isoformat())
        if current is None:
            continue
        candidates = [
            value for key, value in by_period.items()
            if 360 <= (end - date.fromisoformat(key)).days <= 371
        ]
        if len(candidates) != 1:
            continue
        prior_equity = candidates[0]
        availability = max(filed, date.fromisoformat(current["filing_date"]),
                           date.fromisoformat(prior_equity["filing_date"]))
        if availability > cutoff:
            continue
        average = (float(current["value"]) + float(prior_equity["value"])) / 2
        if average <= 0:
            continue
        income = row.get("value")
        if not isinstance(income, (int, float)) or isinstance(income, bool):
            continue
        output.append({
            "report_period": end.isoformat(),
            "filing_date": availability.isoformat(),
            "return_on_equity": income / average,
            "method": "ttm_net_income_over_beginning_and_ending_equity",
            "sources": [*row["components"], current["source"], prior_equity["source"]],
        })
    return sorted(output, key=lambda item: item["report_period"], reverse=True)
