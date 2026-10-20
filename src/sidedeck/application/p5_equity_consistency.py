"""Diagnostic consistency checks on same-accession SOFI capital facts.

A coherent set of XBRL figures is not an accounting opinion. Never approves BVPS.
"""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
from typing import Any

TAGS = ("StockholdersEquity", "CommonStockSharesOutstanding", "CommonStockSharesIssued")


def audit_equity_consistency(bridge: dict[str, Any], joined: dict[str, Any]) -> dict[str, Any]:
    if any(x.get("ticker") != "SOFI" or x.get("buffett_ready") is not False
           or x.get("broker_execution") != "DISABLED" for x in (bridge, joined)):
        raise ValueError("issuer or safety gate mismatch")
    if bridge.get("as_of") != joined.get("as_of"):
        raise ValueError("evidence cutoff mismatch")
    left = bridge.get("observations")
    right = joined.get("observations")
    if not isinstance(left, list) or not isinstance(right, list) or len(left) != len(right) or bridge.get("periods") != len(left) or joined.get("buffett_periods") != len(right):
        raise ValueError("incomplete evidence")
    def indexed(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        result = {}
        for record in records:
            period = record.get("report_period")
            if not isinstance(period, str) or period in result:
                raise ValueError("duplicate/invalid reporting period")
            result[period] = record
        return result
    left_by = indexed(left)
    right_by = indexed(right)
    if set(left_by) != set(right_by):
        raise ValueError("period mismatch")
    outputs = []
    for period in sorted(left_by, reverse=True):
        row = left_by[period]
        source = right_by[period]
        if row.get("mapped_to_buffett") is not False or source.get("mapped_to_buffett") is not False:
            raise ValueError("mapped evidence prohibited")
        facts = row.get("matching_capital_facts")
        if not isinstance(facts, list):
            raise ValueError("missing fact collection")
        values: dict[str, set[int | float]] = {t: set() for t in TAGS}
        for fact in facts:
            tag = fact.get("tag")
            value = fact.get("value")
            if tag not in TAGS:
                continue
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value)):
                raise ValueError("invalid capital value")
            values[tag].add(value)
        issues = []
        if any(len(v) > 1 for v in values.values()):
            issues.append("CONFLICTING_SAME_ACCESSION_VALUES")
        for tag in TAGS:
            if not values[tag]:
                issues.append("MISSING_" + tag.upper())
        outstanding = values["CommonStockSharesOutstanding"]
        issued = values["CommonStockSharesIssued"]
        if len(outstanding) == 1 and len(issued) == 1 and next(iter(outstanding)) > next(iter(issued)):
            issues.append("OUTSTANDING_EXCEEDS_ISSUED")
        equity = values["StockholdersEquity"]
        share = outstanding
        if len(equity) == 1 and len(share) == 1 and next(iter(share)) > 0:
            implied = next(iter(equity)) / next(iter(share))
            preview = source.get("bvps_preview")
            if (isinstance(preview, bool) or not isinstance(preview, (int, float))
                    or not math.isfinite(preview) or not math.isclose(implied, preview, rel_tol=1e-4, abs_tol=1e-6)):
                issues.append("BVPS_PREVIEW_NOT_RECONCILED")
        else:
            issues.append("BVPS_NUMERATOR_DENOMINATOR_NOT_RECONCILED")
        outputs.append({"report_period": period, "issue_codes": sorted(set(issues)),
                        "consistent_source_fact_values": not bool(issues),
                        "preferred_equity_review_required": True,
                        "corporate_actions_review_required": True,
                        "decision": "REQUIRES_REVIEW" if source.get("bvps_preview") is not None else "REJECTED",
                        "mapped_to_buffett": False})
    return {"ticker": "SOFI", "as_of": bridge["as_of"], "observations": outputs,
            "total_periods": len(outputs),
            "periods_with_diagnostic_issues": sum(bool(r["issue_codes"]) for r in outputs),
            "approved_periods": 0, "buffett_ready": False, "assessment": "NO_GO",
            "broker_execution": "DISABLED",
            "note": "Diagnostic only: consistency does not verify preferred classes, financial statement meaning or corporate actions."}


def main() -> int:
    p = argparse.ArgumentParser(description="Diagnostic SEC capital consistency audit")
    p.add_argument("--equity-bridge", required=True)
    p.add_argument("--joined-audit", required=True)
    p.add_argument("--output", required=True)
    a = p.parse_args()
    target = Path(a.output)
    if target.exists():
        p.error("refusing to overwrite evidence")
    result = audit_equity_consistency(
        json.loads(Path(a.equity_bridge).read_text(encoding="utf-8")),
        json.loads(Path(a.joined_audit).read_text(encoding="utf-8")))
    target.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("TOTAL_PERIODS=" + str(result["total_periods"]))
    print("PERIODS_WITH_DIAGNOSTIC_ISSUES=" + str(result["periods_with_diagnostic_issues"]))
    print("APPROVED=0; BROKER_EXECUTION=DISABLED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
