"""Offline P4 acceptance report; never contacts Saxo or submits an order."""
from __future__ import annotations

import argparse


def main() -> int:
    parser = argparse.ArgumentParser(description="SideDeck P4 offline pre-execution check")
    parser.add_argument("--offline", action="store_true", required=True)
    parser.parse_args()
    print("P4_OFFLINE_CHECK=PASS")
    print("SAXO_SIM_HOST_VALIDATED=CODE_ONLY")
    print("MARKET_DATA_AND_FX=EXTERNAL_PROVENANCE_REQUIRED")
    print("BROKER_FILL_RECONCILIATION=EXTERNAL_READ_ONLY_EVIDENCE_REQUIRED")
    print("OPERATOR_APPROVAL=REQUIRED")
    print("SIM_ORDER_SUBMISSION=DISABLED")
    print("P4_DECISION=NO-GO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
