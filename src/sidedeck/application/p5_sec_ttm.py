"""Conservative, provenance-preserving SEC XBRL year-to-date to TTM converter.

Uses *one* cash-flow metric (net income), never fabricates other Buffett
fundamentals or silently substitutes annual values for quarterly snapshots.
"""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

from sidedeck.application.p5_sec_edgar import download_company_facts


class TTMUnavailable(ValueError):
    pass


def _observations(payload: dict[str, Any], cutoff: date) -> list[dict[str, Any]]:
    tag = payload.get("facts", {}).get("us-gaap", {}).get("NetIncomeLoss", {})
    entries = tag.get("units", {}).get("USD", [])
    out: list[dict[str, Any]] = []
    for item in entries:
        if not isinstance(item, dict) or item.get("form") not in ("10-K", "10-Q"):
            continue
        if not all(key in item for key in ("start", "end", "filed", "accn", "val")):
            continue
        try:
            start, end, filed = (date.fromisoformat(item[key]) for key in ("start", "end", "filed"))
        except (TypeError, ValueError):
            continue
        if filed > cutoff or filed < end or start > end:
            continue
        if isinstance(item["val"], bool) or not isinstance(item["val"], (float, int)):
            continue
        duration = (end - start).days
        if not 75 <= duration <= 380:
            continue
        out.append({"start": start, "end": end, "filed": filed,
                    "value": item["val"], "accn": item["accn"],
                    "form": item["form"]})
    return out


def derive_ttm_net_income(payload: dict[str, Any], as_of: str) -> list[dict[str, Any]]:
    """Compute quarterly TTM = annual FY + current YTD - prior FY YTD.

    Requires the three statements' periods to line up and be public by as_of.
    No carry-forward, no guessed missing quarter or use of later amendments.
    """
    cutoff = date.fromisoformat(as_of)
    obs = _observations(payload, cutoff)
    by_period: dict[tuple[date, date], dict[str, Any]] = {}
    for row in obs:
        key = (row["start"], row["end"])
        prior = by_period.get(key)
        if prior is None or row["filed"] < prior["filed"]:
            by_period[key] = row
    yearly = sorted((r for r in by_period.values()
                     if r["form"] == "10-K" and 330 <= (r["end"]-r["start"]).days <= 380),
                    key=lambda r: r["end"])
    results: list[dict[str, Any]] = []
    for annual in yearly:
        results.append({
            "report_period": annual["end"].isoformat(), "value": annual["value"],
            "filing_date": annual["filed"].isoformat(), "period": "ttm",
            "components": [_source(annual)],
        })
    for current in by_period.values():
        if current["form"] != "10-Q":
            continue
        for fy in yearly:
            if not 0 < (current["end"] - fy["end"]).days <= 300:
                continue
            if not 75 <= (current["end"] - current["start"]).days <= 300:
                continue
            prior_ytd = next((p for p in by_period.values()
                if p["start"] == fy["start"] and 360 <= (current["end"] - p["end"]).days <= 370
                and abs((p["end"] - p["start"]).days - (current["end"] - current["start"]).days) <= 8
                and p["form"] == "10-Q"), None)
            if prior_ytd is None:
                continue
            filing = max(fy["filed"], current["filed"], prior_ytd["filed"])
            if filing > cutoff:
                continue
            results.append({
                "report_period": current["end"].isoformat(),
                "filing_date": filing.isoformat(),
                "period": "ttm",
                "value": fy["value"] + current["value"] - prior_ytd["value"],
                "components": [_source(fy), _source(current), _source(prior_ytd)],
            })
            break
    unique: dict[str, dict[str, Any]] = {}
    for record in results:
        key = record["report_period"]
        if key not in unique or record["filing_date"] < unique[key]["filing_date"]:
            unique[key] = record
    return sorted(unique.values(), key=lambda x: x["report_period"], reverse=True)


def _source(row: dict[str, Any]) -> dict[str, Any]:
    return {"accession": row["accn"], "filed": row["filed"].isoformat(),
            "start": row["start"].isoformat(), "end": row["end"].isoformat(),
            "form": row["form"], "tag": "NetIncomeLoss", "unit": "USD"}


def main() -> int:
    parser = argparse.ArgumentParser(description="SEC point-in-time net-income TTM research preview")
    parser.add_argument("--cik", type=int, required=True)
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--user-agent", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    target = Path(args.output)
    if target.exists():
        parser.error("refusing to overwrite existing output")
    raw = download_company_facts(args.cik, args.user_agent, args.as_of)
    records = derive_ttm_net_income(raw, args.as_of)
    if not records:
        raise TTMUnavailable("no independently supported net-income TTM records")
    target.write_text(json.dumps({
        "ticker": args.ticker, "cik": args.cik, "as_of": args.as_of,
        "metric": "net_income", "source": "SEC Company Facts / NetIncomeLoss",
        "research_only": True, "buffett_ready": False,
        "records": records,
    }, indent=2), encoding="utf-8")
    print(f"TTM_NET_INCOME_RECORDS={len(records)}")
    print("BUFFETT_SNAPSHOT=NOT_READY; BROKER_EXECUTION=DISABLED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
