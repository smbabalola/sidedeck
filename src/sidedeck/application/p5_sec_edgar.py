"""SEC Company Facts ingestion for filing-dated, annual cash-flow research.

Strictly separates verified SEC facts from derived TTM series. This initial
adapter exports ONLY annual 10-K records and does not mislabel them TTM.
"""
from __future__ import annotations

import argparse
import json
import re
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any


class SECDataError(ValueError):
    pass


_ALLOWED_HOST = "https://data.sec.gov/api/xbrl/companyfacts/"
_TAGS = {
    "revenues": ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"),
    "net_income": ("NetIncomeLoss",),
    "assets": ("Assets",),
    "liabilities": ("Liabilities",),
    "operating_cash_flow": ("NetCashProvidedByUsedInOperatingActivities",),
}


def extract_annual_facts(payload: dict[str, Any], as_of: str) -> list[dict[str, Any]]:
    """Annual filed 10-K facts, never claim these are trailing twelve months."""
    cutoff = date.fromisoformat(as_of)
    usgaap = payload.get("facts", {}).get("us-gaap", {})
    if not isinstance(usgaap, dict):
        raise SECDataError("missing US GAAP facts")
    values: dict[str, dict[str, dict[str, Any]]] = {}
    for field, tags in _TAGS.items():
        periods: dict[str, dict[str, Any]] = {}
        for tag in tags:
            data = usgaap.get(tag, {})
            for unit, entries in data.get("units", {}).items():
                if unit != "USD" or not isinstance(entries, list):
                    continue
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    if entry.get("form") != "10-K" or not entry.get("accn"):
                        continue
                    try:
                        filed = date.fromisoformat(entry["filed"])
                        end = date.fromisoformat(entry["end"])
                    except (ValueError, KeyError, TypeError):
                        continue
                    if filed > cutoff or filed < end:
                        continue
                    start = entry.get("start")
                    if start is not None:
                        try:
                            duration = (end - date.fromisoformat(start)).days
                        except (ValueError, TypeError):
                            continue
                        if not 330 <= duration <= 380:
                            continue
                    elif field in ("revenues", "net_income", "operating_cash_flow"):
                        continue
                    value = entry.get("val")
                    if isinstance(value, bool) or not isinstance(value, (int, float)):
                        continue
                    # Pick earliest publicly filed version, not a restatement in a later year.
                    current = periods.get(entry["end"])
                    if current is None or entry["filed"] < current["filing_date"]:
                        periods[entry["end"]] = {
                            "value": value, "filing_date": entry["filed"],
                            "accession": entry["accn"], "tag": tag,
                        }
        values[field] = periods
    ends = sorted({end for series in values.values() for end in series}, reverse=True)
    rows: list[dict[str, Any]] = []
    for period_end in ends:
        row = {"report_period": period_end, "period": "annual",
               "metrics": {k: values[k][period_end] for k in _TAGS if period_end in values[k]}}
        if row["metrics"]:
            rows.append(row)
    return rows


def download_company_facts(cik: int, user_agent: str, as_of: str) -> dict[str, Any]:
    """One HTTPS SEC request with declared identity and a bounded timeout."""
    if not 1 <= cik <= 9999999999:
        raise SECDataError("invalid CIK")
    if not user_agent.strip() or "@" not in user_agent:
        raise SECDataError("SEC requires a meaningful contact User-Agent")
    date.fromisoformat(as_of)
    url = f"{_ALLOWED_HOST}CIK{cik:010d}.json"
    request = urllib.request.Request(url, headers={
        "User-Agent": user_agent, "Accept": "application/json",
    })
    with urllib.request.urlopen(request, timeout=20) as response:
        if response.status != 200:
            raise SECDataError("SEC data endpoint unavailable")
        data = response.read(20_000_001)
    if len(data) > 20_000_000:
        raise SECDataError("SEC response too large")
    payload = json.loads(data)
    if not isinstance(payload, dict) or payload.get("cik") != cik:
        raise SECDataError("SEC CIK mismatch")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="SEC 10-K annual facts provenance, NOT TTM")
    parser.add_argument("--cik", required=True, type=int)
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--user-agent", required=True, help="name and valid contact email")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Z][A-Z0-9.-]*", args.ticker):
        parser.error("invalid ticker")
    target = Path(args.output)
    if target.exists():
        parser.error("refusing to overwrite an existing export")
    payload = download_company_facts(args.cik, args.user_agent, args.as_of)
    exported = {
        "ticker": args.ticker, "cik": args.cik, "as_of": args.as_of,
        "source": f"{_ALLOWED_HOST}CIK{args.cik:010d}.json",
        "frequency": "annual", "research_only": True,
        "records": extract_annual_facts(payload, args.as_of),
    }
    target.write_text(json.dumps(exported, indent=2), encoding="utf-8")
    print(f"SEC annual facts saved: {target}; records={len(exported['records'])}")
    print("TTM_CONVERSION=NOT_IMPLEMENTED")
    print("BROKER_EXECUTION=DISABLED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
