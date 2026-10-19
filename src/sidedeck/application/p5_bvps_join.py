"""Join preliminary SEC BVPS to Buffett periods without enabling it for scoring."""
from __future__ import annotations

import argparse
import json
import math
from datetime import date
from pathlib import Path
from typing import Any


class BVPSJoinError(ValueError):
    pass


def reconcile_bvps(coverage: dict[str, Any], bvps: dict[str, Any]) -> dict[str, Any]:
    try:
        cutoff = date.fromisoformat(coverage["as_of"])
        source_cutoff = date.fromisoformat(bvps["as_of"])
        periods = coverage["periods"]
        observations = bvps["observations"]
    except (KeyError, TypeError, ValueError) as exc:
        raise BVPSJoinError("invalid source report") from exc
    if (source_cutoff != cutoff or not isinstance(periods, list)
            or not isinstance(observations, list)
            or coverage.get("complete_period_count") != len(periods)
            or bvps.get("matched_periods") != len(observations)
            or bvps.get("buffett_ready") is not False
            or bvps.get("broker_execution") != "DISABLED"):
        raise BVPSJoinError("inconsistent or unguarded evidence")
    index: dict[str, dict[str, Any]] = {}
    for row in observations:
        try:
            period = date.fromisoformat(row["report_period"])
            available = date.fromisoformat(row["available_from"])
            equity = row["equity_source"]
            shares = row["shares_source"]
            value = row["book_value_per_share_preview"]
            equity_date = date.fromisoformat(equity["filed"])
            shares_date = date.fromisoformat(shares["filed"])
        except (KeyError, TypeError, ValueError) as exc:
            raise BVPSJoinError("invalid BVPS observation") from exc
        if (row.get("approval") != "UNVERIFIED"
                or not period <= equity_date <= available <= cutoff
                or not period <= shares_date <= available
                or available != max(equity_date, shares_date)
                or isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value <= 0
                or equity.get("accession") != shares.get("accession")
                or equity.get("tag") != "StockholdersEquity"
                or equity.get("unit") != "USD"
                or shares.get("tag") not in ("CommonStockSharesOutstanding",
                                              "EntityCommonStockSharesOutstanding")
                or shares.get("unit") != "shares"
                or row["report_period"] in index):
            raise BVPSJoinError("unsupported or duplicate BVPS evidence")
        index[row["report_period"]] = row
    results = []
    seen: set[str] = set()
    for entry in periods:
        try:
            period = date.fromisoformat(entry["report_period"])
            available = date.fromisoformat(entry["available_from"])
        except (KeyError, TypeError, ValueError) as exc:
            raise BVPSJoinError("invalid Buffett period") from exc
        if not period <= available <= cutoff or entry["report_period"] in seen:
            raise BVPSJoinError("future or duplicate Buffett period")
        seen.add(entry["report_period"])
        matched = index.get(entry["report_period"])
        results.append({
            "report_period": entry["report_period"],
            "bvps_preview": matched["book_value_per_share_preview"] if matched else None,
            "bvps_available_from": matched["available_from"] if matched else None,
            "equity_source": matched["equity_source"] if matched else None,
            "shares_source": matched["shares_source"] if matched else None,
            "mapped_to_buffett": False,
            "reason": ("preferred_equity_and_share_basis_unverified" if matched
                       else "no_matching_filed_bvps_evidence"),
        })
    return {
        "ticker": coverage.get("ticker"), "as_of": cutoff.isoformat(),
        "buffett_periods": len(results),
        "bvps_matched_periods": sum(x["bvps_preview"] is not None for x in results),
        "observations": results, "assessment": "NO_GO",
        "buffett_ready": False, "broker_execution": "DISABLED",
        "note": "BVPS remains in the audit only, not the upstream Buffett FinancialMetrics input.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit-only SEC BVPS to Buffett-period reconciliation")
    parser.add_argument("--quarterly-coverage", required=True)
    parser.add_argument("--bvps-evidence", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    destination = Path(args.output)
    if destination.exists():
        parser.error("refusing to overwrite evidence")
    coverage = json.loads(Path(args.quarterly_coverage).read_text(encoding="utf-8"))
    bvps = json.loads(Path(args.bvps_evidence).read_text(encoding="utf-8"))
    result = reconcile_bvps(coverage, bvps)
    destination.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("BUFFETT_PERIODS=" + str(result["buffett_periods"]))
    print("MATCHED_BVPS_PREVIEWS=" + str(result["bvps_matched_periods"]))
    print("BVPS_MAPPED_TO_BUFFETT=FALSE; BROKER_EXECUTION=DISABLED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
