"""Conservative point-in-time multi-metric SEC research preview.

Do not confuse observations with a Buffett-ready snapshot: availability,
denominators, per-share adjustments, and quarterly compatibility require audit.
"""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

from sidedeck.application.p5_sec_edgar import download_company_facts
from sidedeck.application.p5_sec_ttm import derive_ttm_net_income
from sidedeck.application.p5_sec_derived import cash_flow_ttm, roe_from_filed_equity


_USD_FLOW_TAGS = {
    "net_income": "NetIncomeLoss",
    "operating_cash_flow": "NetCashProvidedByUsedInOperatingActivities",
}
_USD_INSTANT_TAGS = {
    "assets": "Assets",
    "liabilities": "Liabilities",
    "stockholders_equity": "StockholdersEquity",
}


def _first_public_observations(
    payload: dict[str, Any], tag: str, as_of: date, *, instant: bool
) -> list[dict[str, Any]]:
    data = payload.get("facts", {}).get("us-gaap", {}).get(tag, {})
    values: dict[str, dict[str, Any]] = {}
    for raw in data.get("units", {}).get("USD", []):
        if not isinstance(raw, dict) or raw.get("form") not in ("10-K", "10-Q"):
            continue
        try:
            filed, end = date.fromisoformat(raw["filed"]), date.fromisoformat(raw["end"])
            start = date.fromisoformat(raw["start"]) if "start" in raw else None
        except (KeyError, ValueError, TypeError):
            continue
        if filed > as_of or filed < end or (start is None) != instant:
            continue
        if start is not None and not 75 <= (end - start).days <= 380:
            continue
        if not raw.get("accn") or isinstance(raw.get("val"), bool) or not isinstance(raw.get("val"), (int, float)):
            continue
        period = end.isoformat()
        item = {
            "report_period": period, "filing_date": filed.isoformat(),
            "value": raw["val"],
            "source": {
                "accession": raw["accn"], "form": raw["form"],
                "filed": filed.isoformat(), "end": period,
                "tag": tag, "unit": "USD",
            },
        }
        if start is not None:
            item["source"]["start"] = start.isoformat()
        if period not in values or item["filing_date"] < values[period]["filing_date"]:
            values[period] = item
    return sorted(values.values(), key=lambda v: v["report_period"], reverse=True)


def preview_multimetric(payload: dict[str, Any], as_of: str) -> dict[str, Any]:
    cutoff = date.fromisoformat(as_of)
    result: dict[str, Any] = {}
    net_income = derive_ttm_net_income(payload, as_of)
    result["net_income_ttm"] = net_income
    for key, tag in _USD_FLOW_TAGS.items():
        result[key + "_reported"] = _first_public_observations(payload, tag, cutoff, instant=False)
    for key, tag in _USD_INSTANT_TAGS.items():
        result[key + "_instant"] = _first_public_observations(payload, tag, cutoff, instant=True)
    result["operating_cash_flow_ttm"] = cash_flow_ttm(payload, as_of)
    result["return_on_equity_preview"] = roe_from_filed_equity(
        net_income, result["stockholders_equity_instant"], as_of,
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="SEC multi-metric research preview (not Buffett-ready)")
    parser.add_argument("--cik", type=int, required=True)
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--user-agent", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    target = Path(args.output)
    if target.exists():
        parser.error("refusing to overwrite existing output")
    data = download_company_facts(args.cik, args.user_agent, args.as_of)
    report = {
        "ticker": args.ticker, "cik": args.cik, "as_of": args.as_of,
        "source": "SEC Company Facts", "research_only": True,
        "buffett_ready": False,
        "metrics": preview_multimetric(data, args.as_of),
    }
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("SEC_MULTIMETRIC_PREVIEW=SAVED")
    print("BUFFETT_SNAPSHOT=NOT_READY; BROKER_EXECUTION=DISABLED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
