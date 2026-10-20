"""Consolidated fail-closed BVPS evidence decision; never authorizes Buffett scores.

Consumes existing audits without inventing equity adjustments or corporate actions.
"""
from __future__ import annotations
import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any, cast


class BVPSGateError(ValueError):
    pass


def consolidate_bvps(joined: dict[str, Any], accounting: dict[str, Any], preferred: dict[str, Any], disclosures: dict[str, Any]) -> dict[str, Any]:
    inputs = (joined, accounting, preferred, disclosures)
    if any(x.get("ticker") != "SOFI" or x.get("buffett_ready") is not False
           or x.get("broker_execution") != "DISABLED" for x in inputs):
        raise BVPSGateError("issuer or NO-GO contract mismatch")
    asof = joined.get("as_of")
    date.fromisoformat(str(asof))
    if any(x.get("as_of") != asof for x in inputs):
        raise BVPSGateError("inconsistent evidence cutoff")
    expected = joined.get("buffett_periods")
    if not isinstance(expected, int) or isinstance(expected, bool) or expected < 1:
        raise BVPSGateError("invalid period count")
    def index(payload: dict[str, Any], key: str) -> dict[str, dict[str, Any]]:
        entries = payload.get(key)
        if not isinstance(entries, list) or len(entries) != expected:
            raise BVPSGateError("incomplete evidence history")
        result = {}
        for row in entries:
            period = row.get("report_period")
            if not isinstance(period, str) or period in result:
                raise BVPSGateError("duplicate or invalid period")
            date.fromisoformat(period)
            result[period] = row
        return result
    base = index(joined, "observations")
    acc = index(accounting, "observations")
    pref = index(preferred, "periods")
    disc = index(disclosures, "observations")
    if set(base) != set(acc) or set(base) != set(pref) or set(base) != set(disc):
        raise BVPSGateError("different historical periods across audits")
    rows = []
    for period in sorted(base, reverse=True):
        b, a, p, d = base[period], acc[period], pref[period], disc[period]
        if any(x.get("mapped_to_buffett") is not False for x in (b, a, p, d)):
            raise BVPSGateError("unapproved value previously mapped")
        if a.get("decision") == "APPROVED" or d.get("decision") == "APPROVED":
            raise BVPSGateError("unsupported prior approval")
        present = b.get("bvps_preview") is not None
        if present and (a.get("decision") != "REQUIRES_REVIEW"
                        or p.get("decision") != "REQUIRES_REVIEW"
                        or d.get("decision") != "REQUIRES_REVIEW"):
            raise BVPSGateError("contradictory evidence decisions")
        if not present and (a.get("decision") != "REJECTED"
                            or p.get("decision") != "REJECTED"
                            or d.get("decision") != "REJECTED"):
            raise BVPSGateError("contradictory rejected history")
        reasons = (["COMMON_EQUITY_BRIDGE_UNVERIFIED",
                    "PREFERRED_CLASS_COMPLETENESS_UNVERIFIED",
                    "HISTORICAL_SHARE_COMPARABILITY_UNVERIFIED"]
                   if present else ["NO_MATCHING_BVPS"])
        rows.append({
            "report_period": period, "bvps_preview": b.get("bvps_preview"),
            "decision": "REQUIRES_REVIEW" if present else "REJECTED",
            "reason_codes": reasons,
            "preferred_balance_fact_count": len(p.get("preferred_balance_facts", [])),
            "preferred_transaction_fact_count": len(p.get("preferred_transaction_facts", [])),
            "filing_disclosures": d.get("filing_disclosures", []),
            "equity_source": b.get("equity_source"),
            "shares_source": b.get("shares_source"),
            "approved_for_buffett": False,
        })
    return {
        "ticker": "SOFI", "as_of": asof, "periods": rows,
        "total_periods": len(rows), "approved_periods": 0,
        "requires_review_periods": sum(x["decision"] == "REQUIRES_REVIEW" for x in rows),
        "rejected_periods": sum(x["decision"] == "REJECTED" for x in rows),
        "assessment": "NO_GO", "buffett_ready": False, "broker_execution": "DISABLED",
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Consolidated research-only BVPS accounting gate")
    for flag in ("joined-audit", "accounting-review", "preferred-audit", "disclosure-review", "output"):
        p.add_argument("--" + flag, required=True)
    a = p.parse_args()
    out = Path(a.output)
    if out.exists():
        p.error("refusing to overwrite evidence")
    def load(path: str) -> dict[str, Any]:
        return cast(dict[str, Any], json.loads(Path(path).read_text(encoding="utf-8")))
    result = consolidate_bvps(load(a.joined_audit), load(a.accounting_review),
                              load(a.preferred_audit), load(a.disclosure_review))
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("BVPS_REQUIRES_REVIEW=" + str(result["requires_review_periods"]))
    print("BVPS_APPROVED=0; BROKER_EXECUTION=DISABLED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
