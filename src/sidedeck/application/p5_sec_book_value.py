"""Conservative book-value-per-share reconciliation from SEC filed instant facts.

Not a Buffett mapper: produces an audit only, never approves financial research.
"""
from __future__ import annotations

import math
from datetime import date
from typing import Any


class BookValueEvidenceError(ValueError):
    pass


def _facts(payload: dict[str, Any], namespace: str, tag: str, unit: str, cutoff: date) -> dict[str, dict[str, Any]]:
    items = payload.get("facts", {}).get(namespace, {}).get(tag, {}).get("units", {}).get(unit, [])
    chosen: dict[str, dict[str, Any]] = {}
    for row in items:
        if not isinstance(row, dict) or row.get("form") not in ("10-K", "10-Q") or "start" in row:
            continue
        try:
            end = date.fromisoformat(row["end"])
            filed = date.fromisoformat(row["filed"])
        except (KeyError, ValueError, TypeError):
            continue
        value = row.get("val")
        if not end <= filed <= cutoff or isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if not math.isfinite(value) or value <= 0 or not isinstance(row.get("accn"), str):
            continue
        evidence = {"report_period": end.isoformat(), "filing_date": filed.isoformat(),
                    "value": value, "source": {"accession": row["accn"],
                    "filed": filed.isoformat(), "form": row["form"], "tag": tag,
                    "namespace": namespace, "unit": unit}}
        previous = chosen.get(end.isoformat())
        if previous is None or filed.isoformat() < previous["filing_date"]:
            chosen[end.isoformat()] = evidence
    return chosen


def book_value_per_share_evidence(companyfacts: dict[str, Any], as_of: str) -> dict[str, Any]:
    """Match exact report dates, filing availability and common-share units.

    Reject ambiguous accession mismatches: share counts from DEI cover the
    registrant and may be dated after a financial statement balance sheet.
    """
    cutoff = date.fromisoformat(as_of)
    equity = _facts(companyfacts, "us-gaap", "StockholdersEquity", "USD", cutoff)
    shares_gaap = _facts(companyfacts, "us-gaap", "CommonStockSharesOutstanding", "shares", cutoff)
    shares_dei = _facts(companyfacts, "dei", "EntityCommonStockSharesOutstanding", "shares", cutoff)
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    for period, equity_item in sorted(equity.items(), reverse=True):
        candidates = [s for s in (shares_gaap.get(period), shares_dei.get(period)) if s is not None]
        eligible = [s for s in candidates if s["source"]["accession"] == equity_item["source"]["accession"]]
        if len(eligible) != 1:
            rejected.append({"report_period": period, "reason": "missing_or_ambiguous_same_period_same_filing_shares"})
            continue
        shares = eligible[0]
        accepted.append({
            "report_period": period,
            "available_from": max(equity_item["filing_date"], shares["filing_date"]),
            "book_value_per_share_preview": equity_item["value"] / shares["value"],
            "equity_source": equity_item["source"],
            "shares_source": shares["source"],
            "approval": "UNVERIFIED",
        })
    return {"as_of": cutoff.isoformat(), "matched_periods": len(accepted),
            "observations": accepted, "rejected": rejected, "buffett_ready": False,
            "broker_execution": "DISABLED",
            "note": "Total stockholders equity / exact-date common shares; does not adjust preferred equity or validate split basis."}
