"""Primary-filing disclosure cross-check for SOFI BVPS (offline, no trading).

A few verified primary-source statements narrow review questions. They do not
automatically certify all historical common equity or corporate actions.
"""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any


DISCLOSURES = (
    {"period": "2024-06-30", "fact": "series1_fully_redeemed",
     "date": "2024-06-30", "shares": 0,
     "filing": "https://www.sec.gov/Archives/edgar/data/1818874/000181887424000175/sofi-20240630.htm",
     "detail": "May 2024 redeemed 3,234,000 Series 1 shares; temporary equity; none remained June 30"},
    {"period": "2025-06-30", "fact": "series1_temporary_equity_historical",
     "date": "2025-06-30",
     "filing": "https://www.sec.gov/Archives/edgar/data/1818874/000181887425000180/sofi-20250630.htm",
     "detail": "Series 1 was classified as temporary equity through May 2024 redemption"},
    {"period": "2026-06-30", "fact": "common_shares_outstanding",
     "date": "2026-06-30", "shares": 1290312404,
     "filing": "https://www.sec.gov/Archives/edgar/data/1818874/000181887426000054/sofi-20260630.htm",
     "detail": "Equity note states 1,290,312,404 common shares; no non-voting common shares outstanding"},
)


def disclosure_review(joined: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    if joined.get("ticker") != "SOFI" or raw.get("cik") != 1818874:
        raise ValueError("unexpected issuer")
    if joined.get("buffett_ready") is not False or joined.get("broker_execution") != "DISABLED":
        raise ValueError("unsupported approval state")
    cutoff = date.fromisoformat(joined["as_of"])
    periods = joined["observations"]
    if not isinstance(periods, list) or joined.get("buffett_periods") != len(periods):
        raise ValueError("invalid joined evidence count")
    source = raw.get("facts", {}).get("us-gaap", {}).get("CommonStockSharesOutstanding", {}).get("units", {}).get("shares", [])
    rows = []
    for item in periods:
        report = date.fromisoformat(item["report_period"])
        if report > cutoff or item.get("mapped_to_buffett") is not False:
            raise ValueError("invalid research period")
        supporting = [d for d in DISCLOSURES
                      if date.fromisoformat(str(d["date"])) <= cutoff and d["period"] == item["report_period"]]
        sample = [x for x in source if x.get("end") == item["report_period"]
                  and x.get("val") == 1290312404 and x.get("filed", "9999") <= joined["as_of"]]
        share_confirmed = (item["report_period"] == "2026-06-30" and bool(sample))
        rows.append({"report_period": item["report_period"],
                     "filing_disclosures": supporting,
                     "2026_share_count_corrobated": share_confirmed,
                     "decision": "REQUIRES_REVIEW" if item["bvps_preview"] is not None else "REJECTED",
                     "preferred_equity_status": "PARTIAL_DISCLOSURE",
                     "share_basis_status": "PARTIAL_DISCLOSURE" if share_confirmed else "NOT_VERIFIED",
                     "mapped_to_buffett": False})
    return {"ticker": "SOFI", "as_of": joined["as_of"],
            "observations": rows, "approved_periods": 0,
            "review_required": sum(x["decision"] == "REQUIRES_REVIEW" for x in rows),
            "assessment": "NO_GO", "buffett_ready": False, "broker_execution": "DISABLED",
            "limitations": ["2024 Series 1 redemption does not exclude other preferred classes in later periods",
                            "share classes, total/common equity bridges and split basis need complete independent verification"]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--joined-audit", required=True)
    parser.add_argument("--companyfacts", required=True)
    parser.add_argument("--output", required=True)
    a = parser.parse_args()
    target = Path(a.output)
    if target.exists():
        parser.error("refusing to overwrite report")
    joined = json.loads(Path(a.joined_audit).read_text(encoding="utf-8"))
    raw = json.loads(Path(a.companyfacts).read_text(encoding="utf-8"))
    report = disclosure_review(joined, raw)
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("DISCLOSURE_PERIODS=" + str(sum(bool(r["filing_disclosures"]) for r in report["observations"])))
    print("BVPS_REQUIRES_REVIEW=" + str(report["review_required"]))
    print("BVPS_APPROVED=0; BROKER_EXECUTION=DISABLED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
