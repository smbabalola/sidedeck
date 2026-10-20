"""Offline MSFT SEC source inventory; presence is never treated as approval.

Requires a user-supplied local SEC Company Facts JSON file. Makes zero requests.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from sidedeck.application.p5_buffett_coverage import CANDIDATE_CONCEPTS, concept_inventory

MSFT_CIK = 789019


def assess_msft_companyfacts(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("cik") != MSFT_CIK:
        raise ValueError("MSFT company facts must have SEC CIK 789019")
    facts = payload.get("facts")
    if not isinstance(facts, dict) or not isinstance(facts.get("us-gaap"), dict):
        raise ValueError("missing US-GAAP taxonomy")
    inventory = concept_inventory(payload)
    present = {field: [key for key, count in detail["candidates"].items() if count > 0]
               for field, detail in inventory.items()}
    missing = sorted(field for field, candidates in present.items() if not candidates)
    return {
        "ticker": "MSFT", "cik": MSFT_CIK,
        "source": "OWNER_SUPPLIED_LOCAL_SEC_COMPANYFACTS",
        "candidate_concepts": {key: {"found": value, "approved": False}
                               for key, value in present.items()},
        "missing_candidate_fields": missing,
        "candidate_fields_with_some_raw_facts": sum(bool(v) for v in present.values()),
        "total_candidate_fields": len(CANDIDATE_CONCEPTS),
        "point_in_time_eligible": False,
        "ttm_reconciled": False,
        "valuation_approved": False,
        "coverage_gate": "NOT_ASSESSED",
        "research_ready": False,
        "broker_execution": "DISABLED",
        "next_action": "RECONCILE_SEC_PERIODS_AND_METRIC_DEFINITIONS",
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Offline MSFT SEC Company Facts inventory")
    p.add_argument("--companyfacts", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    destination = Path(args.output)
    if destination.exists():
        p.error("refusing to overwrite output")
    payload = json.loads(Path(args.companyfacts).read_text(encoding="utf-8"))
    report = assess_msft_companyfacts(payload)
    destination.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("MSFT_INVENTORY=RECORDED; COVERAGE_GATE=NOT_ASSESSED; BROKER_EXECUTION=DISABLED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
