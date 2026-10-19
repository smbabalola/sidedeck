"""Strict research readiness assessment of SEC preview data, never trade approval."""
from __future__ import annotations

import argparse
import json
import math
from datetime import date
from pathlib import Path
from typing import Any


def _valid(item: Any, cutoff: date) -> bool:
    if not isinstance(item, dict) or not isinstance(item.get("source"), dict):
        return False
    src = item["source"]
    try:
        filed = date.fromisoformat(item["filing_date"])
        period = date.fromisoformat(item["report_period"])
    except (TypeError, ValueError, KeyError):
        return False
    value = item.get("value")
    return (
        filed <= cutoff and filed >= period and src.get("filed") == item["filing_date"]
        and bool(src.get("accession")) and src.get("unit") == "USD"
        and isinstance(value, (int, float)) and not isinstance(value, bool)
        and math.isfinite(value)
    )


def assess_preview(payload: dict[str, Any]) -> dict[str, Any]:
    """Evaluate evidence and ratios without claiming Buffett agent readiness."""
    cutoff = date.fromisoformat(payload["as_of"])
    metrics = payload.get("metrics")
    if not isinstance(metrics, dict):
        raise ValueError("missing metrics object")
    names = ("assets_instant", "liabilities_instant", "stockholders_equity_instant")
    latest: dict[str, dict[str, Any]] = {}
    blockers: list[str] = []
    for name in names:
        records = metrics.get(name, [])
        if not isinstance(records, list):
            blockers.append(name + ":invalid_records")
            continue
        eligible = [r for r in records if _valid(r, cutoff)]
        if not eligible:
            blockers.append(name + ":missing_filed_evidence")
            continue
        latest[name] = max(eligible, key=lambda r: r["report_period"])

    derived: dict[str, Any] = {}
    if len(latest) == len(names):
        periods = {r["report_period"] for r in latest.values()}
        if len(periods) != 1:
            blockers.append("balance_sheet:period_mismatch")
        else:
            assets = float(latest["assets_instant"]["value"])
            liabilities = float(latest["liabilities_instant"]["value"])
            equity = float(latest["stockholders_equity_instant"]["value"])
            if not all(math.isfinite(v) for v in (assets, liabilities, equity)):
                blockers.append("balance_sheet:nonfinite")
            elif assets <= 0 or equity <= 0:
                blockers.append("balance_sheet:nonpositive_denominator")
            else:
                derived["liabilities_to_equity"] = liabilities / equity
                derived["equity_to_assets"] = equity / assets
                derived["balance_sheet_period"] = next(iter(periods))
                derived["sources"] = [latest[k]["source"] for k in names]
                # Do not call liabilities/equity debt-to-equity: liabilities include
                # non-debt obligations. No ROE without average equity and TTM NI.
                if abs(assets - liabilities - equity) > max(1.0, assets * 0.01):
                    blockers.append("balance_sheet:accounting_identity_mismatch")
                    derived.clear()
    net_income = metrics.get("net_income_ttm", [])
    if not isinstance(net_income, list) or len(net_income) < 4:
        blockers.append("net_income_ttm:insufficient_history")
    roe = metrics.get("return_on_equity_preview", [])
    cash = metrics.get("operating_cash_flow_ttm", [])
    if not isinstance(roe, list) or len(roe) < 4:
        blockers.append("return_on_equity:insufficient_filed_history")
    if not isinstance(cash, list) or len(cash) < 4:
        blockers.append("cash_flow_ttm:insufficient_filed_history")
    blockers.extend((
        "price_to_earnings:price_and_share_count_missing",
        "buffett:validated_quarterly_metric_history_missing",
    ))
    return {
        "assessment": "NO_GO",
        "buffett_ready": False,
        "broker_execution": "DISABLED",
        "derived_nontrading_ratios": derived,
        "cash_flow_ttm_records": len(cash) if isinstance(cash, list) else 0,
        "roe_preview_records": len(roe) if isinstance(roe, list) else 0,
        "blockers": sorted(set(blockers)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="No-trade SEC preview evidence gate")
    parser.add_argument("--input", required=True)
    args = parser.parse_args()
    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("invalid preview JSON")
    print(json.dumps(assess_preview(data), indent=2, sort_keys=True))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
