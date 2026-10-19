"""Read-only Saxo SIM account order audit, deliberately not fill reconciliation."""
from __future__ import annotations

import argparse
from typing import Any
from urllib.parse import quote

from sidedeck.infrastructure.saxo_account_scope import SaxoAccountScope, verified_scope
from sidedeck.infrastructure.saxo_sim import SaxoSimClient, SaxoSimError


def audit_path(scope: SaxoAccountScope) -> str:
    return ("/cs/v1/audit/orderactivities?AccountKey="
            + quote(scope.account_key, safe="") + "&ClientKey="
            + quote(scope.client_key, safe="")
            + "&EntryType=Last&IncludeSubAccounts=false&%24top=100")


def summarize_audit(data: dict[str, Any], *, account_id: str) -> tuple[int, int]:
    """Complete page only. Audit activity is not proof of executions or fills."""
    records = data.get("Data")
    if not isinstance(records, list) or len(records) > 100:
        raise ValueError("invalid audit collection")
    count = data.get("__count")
    if (data.get("__next") or data.get("__nextPoll")
            or (type(count) is int and count > len(records))):
        raise ValueError("audit incomplete: pagination or polling required")
    for record in records:
        if not isinstance(record, dict) or record.get("AccountId") != account_id:
            raise ValueError("audit account mismatch")
    references = sum(isinstance(r.get("ExternalReference"), str)
                     and bool(r["ExternalReference"]) for r in records)
    return len(records), references


def main() -> int:
    parser = argparse.ArgumentParser(description="Saxo SIM account audit read only")
    parser.add_argument("--expected-account-id", required=True)
    args = parser.parse_args()
    if args.expected_account_id != "22866064":
        print("BLOCKED: unapproved SIM account")
        return 2
    try:
        client = SaxoSimClient()
        scope = verified_scope(client, args.expected_account_id)
        count, refs = summarize_audit(client.get(audit_path(scope)),
                                      account_id=scope.account_id)
        print(f"Saxo SIM audit activity records={count}; external references={refs}")
        print("Audit snapshot only; individual order fills NOT reconciled.")
        print("NO orders submitted; live and automatic execution disabled.")
        return 0
    except (SaxoSimError, ValueError, PermissionError):
        print("BLOCKED: account-scoped Saxo audit unavailable or incomplete")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
