"""Build a sourced, quarterly SEC metrics coverage report; never fabricate Buffett ratios."""
from __future__ import annotations

import argparse
import json
import math
from datetime import date
from pathlib import Path
from typing import Any


class QuarterlyEvidenceError(ValueError):
    pass


def _records(metrics: dict[str, Any], name: str) -> list[dict[str, Any]]:
    rows = metrics.get(name, [])
    if not isinstance(rows, list):
        raise QuarterlyEvidenceError("invalid metric series: " + name)
    return rows


def quarterly_coverage(preview: dict[str, Any]) -> dict[str, Any]:
    """Intersect SEC-period histories with per-record as-of provenance checks."""
    cutoff = date.fromisoformat(preview["as_of"])
    metrics = preview.get("metrics")
    if not isinstance(metrics, dict):
        raise QuarterlyEvidenceError("missing SEC metrics")
    names = ("net_income_ttm", "operating_cash_flow_ttm",
             "return_on_equity_preview", "stockholders_equity_instant")
    by_name: dict[str, dict[str, dict[str, Any]]] = {}
    for name in names:
        series: dict[str, dict[str, Any]] = {}
        for row in _records(metrics, name):
            if not isinstance(row, dict):
                raise QuarterlyEvidenceError("invalid metric row")
            try:
                period = date.fromisoformat(row["report_period"])
                filed = date.fromisoformat(row["filing_date"])
            except (KeyError, TypeError, ValueError) as exc:
                raise QuarterlyEvidenceError("invalid metric dates") from exc
            if not period <= filed <= cutoff or row["report_period"] in series:
                raise QuarterlyEvidenceError("future, pre-report, or duplicate evidence")
            if name == "return_on_equity_preview":
                value = row.get("return_on_equity")
                components = row.get("sources")
            elif name == "stockholders_equity_instant":
                value = row.get("value")
                components = [row.get("source")]
            else:
                value = row.get("value")
                components = row.get("components")
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) or not isinstance(components, list)
                    or not components):
                raise QuarterlyEvidenceError("invalid value or missing provenance")
            if not all(isinstance(s, dict) and s.get("accession") and s.get("filed")
                       and date.fromisoformat(s["filed"]) <= filed for s in components):
                raise QuarterlyEvidenceError("invalid SEC component provenance")
            series[row["report_period"]] = {"value": value, "filing_date": row["filing_date"],
                                            "sources": components}
        by_name[name] = series
    periods = sorted(set.intersection(*(set(rows) for rows in by_name.values())),
                     reverse=True)
    output = []
    for period in periods:
        matched = {name: by_name[name][period] for name in names}
        available = max(row["filing_date"] for row in matched.values())
        output.append({"report_period": period, "available_from": available,
                       "metrics": matched})
    return {
        "ticker": preview.get("ticker"), "as_of": cutoff.isoformat(),
        "required_series": list(names),
        "complete_period_count": len(output),
        "periods": output, "assessment": "NO_GO",
        "buffett_ready": False, "broker_execution": "DISABLED",
        "missing_buffett_metrics": ["gross_margin", "operating_margin", "net_margin",
                                    "debt_to_equity", "current_ratio", "revenue_growth",
                                    "book_value_per_share", "free_cash_flow_per_share",
                                    "market_cap", "price_to_earnings_ratio"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only SEC quarterly research coverage")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    destination = Path(args.output)
    if destination.exists():
        parser.error("refusing to overwrite existing report")
    raw = json.loads(Path(args.input).read_text(encoding="utf-8"))
    report = quarterly_coverage(raw)
    destination.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("QUARTERLY_COVERAGE_REPORT=SAVED")
    print("COMPLETE_PERIODS=" + str(report["complete_period_count"]))
    print("BUFFETT_READY=FALSE; BROKER_EXECUTION=DISABLED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
