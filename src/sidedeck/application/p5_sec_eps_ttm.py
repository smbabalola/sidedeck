"""Strict SEC EPS reconciliation: only directly filed annual TTM EPS.

Quarter/YTD diluted EPS must not be added or subtracted: dilution denominators
differ and antip-dilution rules can change period to period.
"""
from __future__ import annotations

from datetime import date
from typing import Any


def annual_diluted_eps(payload: dict[str, Any], as_of: str) -> list[dict[str, Any]]:
    """Return directly reported 10-K full-year EPS, with original filing evidence.

    Reporting year-end entries are trailing twelve months by definition.
    Quarter-end TTM EPS remains unavailable until validated share-weighting.
    """
    cutoff = date.fromisoformat(as_of)
    tag = payload.get("facts", {}).get("us-gaap", {}).get("EarningsPerShareDiluted", {})
    chosen: dict[tuple[date, date], dict[str, Any]] = {}
    for row in tag.get("units", {}).get("USD/shares", []):
        if not isinstance(row, dict) or row.get("form") != "10-K":
            continue
        try:
            start, end, filed = (date.fromisoformat(row[key]) for key in ("start", "end", "filed"))
        except (KeyError, TypeError, ValueError):
            continue
        if not 330 <= (end - start).days <= 380 or not end <= filed <= cutoff:
            continue
        value = row.get("val")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if not row.get("accn"):
            continue
        key = (start, end)
        existing = chosen.get(key)
        if existing is None or filed.isoformat() < existing["filing_date"]:
            chosen[key] = {
                "start": start.isoformat(), "report_period": end.isoformat(),
                "filing_date": filed.isoformat(), "eps_ttm": value,
                "method": "directly_filed_full_year_eps_no_quarterly_aggregation",
                "source": {"tag": "EarningsPerShareDiluted", "unit": "USD/shares",
                           "accession": row["accn"], "filed": filed.isoformat(),
                           "start": start.isoformat(), "end": end.isoformat()},
            }
    return sorted(chosen.values(), key=lambda x: x["report_period"], reverse=True)
