"""SOFI BVPS accounting review: conservative research-only decisions."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def review_bvps(joined: dict, raw: dict) -> dict:
    if joined.get("buffett_ready") is not False or joined.get("broker_execution") != "DISABLED":
        raise ValueError("review input must remain unapproved")
    if joined.get("ticker") != "SOFI" or raw.get("cik") != 1818874:
        raise ValueError("unexpected issuer")
    rows = []
    for entry in joined["observations"]:
        present = entry["bvps_preview"] is not None
        rows.append({
            "report_period": entry["report_period"],
            "decision": "REQUIRES_REVIEW" if present else "REJECTED",
            "preferred_equity": "NOT_VERIFIED",
            "share_comparability": "NOT_VERIFIED",
            "mapped_to_buffett": False,
        })
    return {
        "ticker": "SOFI", "as_of": joined["as_of"],
        "observations": rows,
        "approved_periods": 0,
        "requires_review_periods": sum(x["decision"] == "REQUIRES_REVIEW" for x in rows),
        "rejected_periods": sum(x["decision"] == "REJECTED" for x in rows),
        "assessment": "NO_GO", "buffett_ready": False,
        "broker_execution": "DISABLED",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--joined-audit", required=True)
    parser.add_argument("--companyfacts", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        parser.error("refusing to overwrite existing audit")
    joined = json.loads(Path(args.joined_audit).read_text(encoding="utf-8"))
    raw = json.loads(Path(args.companyfacts).read_text(encoding="utf-8"))
    result = review_bvps(joined, raw)
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("BVPS_REQUIRES_REVIEW=" + str(result["requires_review_periods"]))
    print("BVPS_APPROVED=0; BROKER_EXECUTION=DISABLED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
