"""Inventory SOFI SEC capital facts without inferring zero preferred stock.

SEC Company Facts may omit class-specific and custom extension disclosures;
absence is not evidence of no preferred stock or no share splits.
"""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any


PREFERRED_TERMS = ("preferredstock", "preferredshares", "convertiblepreferred")
SHARE_TERMS = ("commonstocksharesoutstanding", "entitycommonstocksharesoutstanding",
               "commonstocksharesissued", "stocksplit", "stockdividend")


def capital_inventory(raw: dict[str, Any], as_of: str) -> dict[str, Any]:
    if raw.get("cik") != 1818874 or not isinstance(raw.get("facts"), dict):
        raise ValueError("expected SOFI SEC Company Facts")
    cutoff = date.fromisoformat(as_of)
    observations: list[dict[str, Any]] = []
    for namespace, facts in raw["facts"].items():
        if not isinstance(facts, dict):
            continue
        for tag, item in facts.items():
            lowered = tag.lower()
            if not any(word in lowered for word in PREFERRED_TERMS + SHARE_TERMS):
                continue
            for unit, values in item.get("units", {}).items():
                if not isinstance(values, list):
                    continue
                for value in values:
                    if not isinstance(value, dict) or value.get("form") not in ("10-K", "10-Q"):
                        continue
                    try:
                        reported = date.fromisoformat(value["end"])
                        filed = date.fromisoformat(value["filed"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    if not reported <= filed <= cutoff or not value.get("accn"):
                        continue
                    observations.append({
                        "namespace": namespace, "tag": tag, "unit": unit,
                        "report_period": reported.isoformat(),
                        "filing_date": filed.isoformat(),
                        "accession": value["accn"], "value": value.get("val"),
                        "form": value["form"],
                    })
    observations.sort(key=lambda r: (r["report_period"], r["filing_date"], r["tag"]), reverse=True)
    return {
        "ticker": "SOFI", "cik": 1818874, "as_of": cutoff.isoformat(),
        "capital_observations": observations,
        "capital_observation_count": len(observations),
        "preferred_status": "UNDETERMINED",
        "share_class_status": "UNDETERMINED",
        "corporate_action_status": "UNDETERMINED",
        "approved_bvps_periods": 0, "buffett_ready": False,
        "broker_execution": "DISABLED",
        "limitations": [
            "XBRL Company Facts may omit issuer-specific, class-level and narrative disclosures",
            "A missing preferred-stock tag does not establish a zero preferred balance",
            "No stock-split adjustment or common equity bridge has been verified",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline SEC capital tag inventory")
    parser.add_argument("--companyfacts", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    target = Path(args.output)
    if target.exists():
        parser.error("refusing to overwrite evidence")
    raw = json.loads(Path(args.companyfacts).read_text(encoding="utf-8"))
    result = capital_inventory(raw, args.as_of)
    target.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("CAPITAL_OBSERVATIONS=" + str(result["capital_observation_count"]))
    print("PREFERRED_STATUS=UNDETERMINED")
    print("SHARE_CLASS_STATUS=UNDETERMINED")
    print("APPROVED_BVPS_PERIODS=0; BROKER_EXECUTION=DISABLED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
