"""Trace SEC equity numerator to same-filing capital-class facts, fail closed.

This is an evidence bridge, not an accounting approval or Buffett metric export.
"""
from __future__ import annotations
import argparse
import json
import math
from datetime import date
from pathlib import Path
from typing import Any

EQUITY_TAGS = ("StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
               "PreferredStockValue", "RedeemablePreferredStockCarryingAmount",
               "TemporaryEquityCarryingAmountAttributableToParent", "MinorityInterest",
               "StockholdersEquityOther")
SHARE_TAGS = ("CommonStockSharesOutstanding", "CommonStockSharesIssued")


def equity_bridge(joined: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    if (joined.get("ticker") != "SOFI" or raw.get("cik") != 1818874
            or joined.get("buffett_ready") is not False
            or joined.get("broker_execution") != "DISABLED"):
        raise ValueError("issuer or research gate mismatch")
    cutoff = date.fromisoformat(joined["as_of"])
    observations = joined.get("observations")
    if not isinstance(observations, list) or joined.get("buffett_periods") != len(observations):
        raise ValueError("incomplete period coverage")
    facts = raw.get("facts", {}).get("us-gaap", {})
    seen = set()
    rows = []
    for observation in observations:
        period = observation["report_period"]
        if period in seen or date.fromisoformat(period) > cutoff or observation.get("mapped_to_buffett") is not False:
            raise ValueError("duplicate, future or mapped observation")
        seen.add(period)
        equity_source = observation.get("equity_source")
        shares_source = observation.get("shares_source")
        if not equity_source or not shares_source:
            rows.append({"report_period": period, "decision": "REJECTED",
                         "matching_capital_facts": [], "issues": ["MISSING_JOINED_EQUITY_OR_SHARES"],
                         "common_equity_verified": False, "mapped_to_buffett": False})
            continue
        accession = equity_source.get("accession")
        if not isinstance(accession, str) or not accession or shares_source.get("accession") != accession:
            raise ValueError("equity and share source accession mismatch")
        candidates = []
        for tag in EQUITY_TAGS + SHARE_TAGS:
            unit = "shares" if tag in SHARE_TAGS else "USD"
            for fact in facts.get(tag, {}).get("units", {}).get(unit, []):
                if (fact.get("end") != period or fact.get("accn") != accession
                        or fact.get("form") not in ("10-K", "10-Q")):
                    continue
                try:
                    filed = date.fromisoformat(fact["filed"])
                except (KeyError, TypeError, ValueError):
                    continue
                if not date.fromisoformat(period) <= filed <= cutoff:
                    continue
                value = fact.get("val")
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                    continue
                candidates.append({"tag": tag, "value": value, "unit": unit,
                                   "accession": accession, "filed": filed.isoformat()})
        candidates.sort(key=lambda x: (x["tag"], x["value"]))
        rows.append({"report_period": period, "decision": "REQUIRES_REVIEW",
                     "source_accession": accession, "matching_capital_facts": candidates,
                     "issues": ["PREFERRED_AND_REDEEMABLE_CLASSES_REQUIRE_FILING_NOTES",
                                "COMMON_EQUITY_NUMERATOR_NOT_RECONCILED",
                                "SHARE_SPLITS_AND_CLASSES_NOT_CONFIRMED"],
                     "common_equity_verified": False, "mapped_to_buffett": False})
    return {"ticker": "SOFI", "as_of": joined["as_of"], "observations": rows,
            "periods": len(rows), "approved_periods": 0,
            "assessment": "NO_GO", "buffett_ready": False, "broker_execution": "DISABLED",
            "note": "Only facts with the same SEC accession as the joined equity source are included; missing tags are unknown, not zero."}


def main() -> int:
    p = argparse.ArgumentParser(description="SOFI same-filing common equity evidence bridge")
    p.add_argument("--joined-audit", required=True)
    p.add_argument("--companyfacts", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    output = Path(args.output)
    if output.exists():
        p.error("refusing to overwrite evidence")
    joined = json.loads(Path(args.joined_audit).read_text(encoding="utf-8"))
    raw = json.loads(Path(args.companyfacts).read_text(encoding="utf-8"))
    result = equity_bridge(joined, raw)
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("EQUITY_BRIDGE_PERIODS=" + str(result["periods"]))
    print("PERIODS_WITH_SAME_ACCESSION_FACTS=" +
          str(sum(bool(r["matching_capital_facts"]) for r in result["observations"])))
    print("APPROVED=0; BROKER_EXECUTION=DISABLED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
