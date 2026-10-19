"""Audit SOFI preferred-stock filings without treating cash flows as balances."""
from __future__ import annotations
import argparse
import json
from collections import defaultdict
from datetime import date
from pathlib import Path

BALANCE_TAGS = frozenset({"PreferredStockValue", "PreferredStockSharesOutstanding",
                          "PreferredStockSharesIssued", "PreferredStockCarryingValue",
                          "PreferredStockRedemptionValue", "RedeemablePreferredStockCarryingAmount"})
FLOW_TAGS = frozenset({"PaymentsForRepurchaseOfRedeemablePreferredStock",
                       "ProceedsFromIssuanceOfRedeemablePreferredStock",
                       "RedeemablePreferredStockDividends",
                       "PreferredStockDividendsIncomeStatementImpact",
                       "PreferredStockRedemptionPremium"})


def preferred_filing_audit(inventory: dict, joined: dict) -> dict:
    if (inventory.get("cik") != 1818874 or joined.get("ticker") != "SOFI"
            or inventory.get("as_of") != joined.get("as_of")
            or joined.get("buffett_ready") is not False
            or joined.get("broker_execution") != "DISABLED"):
        raise ValueError("invalid issuer, cutoff or approval status")
    cutoff = date.fromisoformat(inventory["as_of"])
    by_period = defaultdict(list)
    for row in inventory["capital_observations"]:
        if row["tag"] not in BALANCE_TAGS | FLOW_TAGS:
            continue
        if not date.fromisoformat(row["report_period"]) <= date.fromisoformat(row["filing_date"]) <= cutoff:
            raise ValueError("future SEC evidence")
        by_period[row["report_period"]].append(row)
    rows = []
    for period in joined["observations"]:
        report = period["report_period"]
        capital = by_period[report]
        balances = [r for r in capital if r["tag"] in BALANCE_TAGS]
        flows = [r for r in capital if r["tag"] in FLOW_TAGS]
        rows.append({"report_period": report,
                     "decision": "REQUIRES_REVIEW" if period["bvps_preview"] is not None else "REJECTED",
                     "preferred_balance_facts": balances,
                     "preferred_transaction_facts": flows,
                     "preferred_balance_validated": False,
                     "share_basis_validated": False,
                     "mapped_to_buffett": False,
                     "reason": "preferred_balance_and_share_class_not_confirmed_from_filing_notes"})
    return {"ticker": "SOFI", "as_of": inventory["as_of"], "periods": rows,
            "approved_periods": 0, "buffett_ready": False, "assessment": "NO_GO",
            "broker_execution": "DISABLED",
            "note": "Transactions and dividends do not establish closing preferred balances; filing footnotes still required."}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--capital-inventory", required=True)
    p.add_argument("--joined-audit", required=True)
    p.add_argument("--output", required=True)
    a = p.parse_args()
    out = Path(a.output)
    if out.exists():
        p.error("refusing to overwrite")
    inventory = json.loads(Path(a.capital_inventory).read_text(encoding="utf-8"))
    joined = json.loads(Path(a.joined_audit).read_text(encoding="utf-8"))
    result = preferred_filing_audit(inventory, joined)
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("PERIODS=" + str(len(result["periods"])))
    print("PREFERRED_BALANCE_EVIDENCE_PERIODS=" +
          str(sum(bool(r["preferred_balance_facts"]) for r in result["periods"])))
    print("PREFERRED_TRANSACTION_EVIDENCE_PERIODS=" +
          str(sum(bool(r["preferred_transaction_facts"]) for r in result["periods"])))
    print("APPROVED_PERIODS=0; BROKER_EXECUTION=DISABLED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
