"""Consolidated SOFI BVPS evidence gate. Never exports unapproved ratios."""
from __future__ import annotations
import argparse
import json
from datetime import date
from pathlib import Path

from sidedeck.application.p5_bvps_join import reconcile_bvps
from sidedeck.application.p5_filing_disclosure_review import disclosure_review
from sidedeck.application.p5_preferred_filing_audit import preferred_filing_audit


def validate_bvps(coverage: dict, bvps: dict, capital: dict, companyfacts: dict) -> dict:
    joined = reconcile_bvps(coverage, bvps)
    if capital.get("as_of") != joined["as_of"] or capital.get("cik") != 1818874:
        raise ValueError("capital inventory mismatch")
    filings = disclosure_review(joined, companyfacts)
    preferred = preferred_filing_audit(capital, joined)
    by_filing = {x["report_period"]: x for x in filings["observations"]}
    by_preferred = {x["report_period"]: x for x in preferred["periods"]}
    if len(by_filing) != joined["buffett_periods"] or len(by_preferred) != joined["buffett_periods"]:
        raise ValueError("duplicate or missing filing evidence")
    rows = []
    for row in joined["observations"]:
        key = row["report_period"]
        f = by_filing[key]
        p = by_preferred[key]
        preview = row["bvps_preview"]
        gaps = (["NO_MATCHING_PRELIMINARY_BVPS"] if preview is None else
                ["COMMON_EQUITY_NUMERATOR_NOT_VERIFIED",
                 "PREFERRED_EQUITY_CLASSIFICATION_NOT_FULLY_VERIFIED",
                 "SHARE_CLASS_AND_CORPORATE_ACTION_BASIS_NOT_VERIFIED"])
        rows.append({
            "report_period": key,
            "decision": "REJECTED" if preview is None else "REQUIRES_REVIEW",
            "preliminary_bvps": preview,
            "available_from": row["bvps_available_from"],
            "equity_source": row["equity_source"],
            "shares_source": row["shares_source"],
            "filing_disclosures": f["filing_disclosures"],
            "preferred_balance_facts": p["preferred_balance_facts"],
            "preferred_transaction_facts": p["preferred_transaction_facts"],
            "evidence_gaps": gaps,
            "mapped_to_buffett": False,
        })
    return {"ticker": "SOFI", "as_of": joined["as_of"],
            "reviewed_periods": len(rows),
            "approved_periods": 0,
            "requires_review_periods": sum(x["decision"] == "REQUIRES_REVIEW" for x in rows),
            "rejected_periods": sum(x["decision"] == "REJECTED" for x in rows),
            "observations": rows, "assessment": "NO_GO",
            "buffett_ready": False, "broker_execution": "DISABLED",
            "note": "Combined audit only. No BVPS metric is added to Buffett until independently verified."}


def main() -> int:
    p = argparse.ArgumentParser(description="Consolidated SEC BVPS research audit")
    p.add_argument("--quarterly-coverage", required=True)
    p.add_argument("--bvps-evidence", required=True)
    p.add_argument("--capital-inventory", required=True)
    p.add_argument("--companyfacts", required=True)
    p.add_argument("--output", required=True)
    a = p.parse_args()
    out = Path(a.output)
    if out.exists():
        p.error("refusing to overwrite previous review")
    def load(path: str) -> dict:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    report = validate_bvps(load(a.quarterly_coverage), load(a.bvps_evidence),
                           load(a.capital_inventory), load(a.companyfacts))
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("REVIEWED_PERIODS=" + str(report["reviewed_periods"]))
    print("REQUIRES_REVIEW=" + str(report["requires_review_periods"]))
    print("REJECTED=" + str(report["rejected_periods"]))
    print("APPROVED=0; BUFFETT_READY=FALSE; BROKER_EXECUTION=DISABLED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
