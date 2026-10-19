"""SideDeck local Saxo SIM access check; no orders or account data printing."""
from __future__ import annotations

import argparse
import os

from sidedeck.infrastructure.saxo_sim import SaxoSimClient, SaxoSimError


def check(client: SaxoSimClient, *, expected_account_id: str) -> tuple[bool, str]:
    if not expected_account_id.strip():
        return False, "expected_sim_account_id_missing"
    user = client.user()
    if not isinstance(user.get("UserKey"), str) or not user["UserKey"]:
        return False, "user_identity_missing"
    accounts = client.accounts()
    records = accounts.get("Data")
    if not isinstance(records, list) or not records:
        return False, "sim_accounts_missing"
    matching = [a for a in records if isinstance(a, dict)
                and a.get("AccountId") == expected_account_id]
    if len(matching) != 1:
        return False, "account_identity_unverified"
    account = matching[0]
    if account.get("Active") is not True:
        return False, "sim_account_inactive"
    if not isinstance(account.get("AccountKey"), str) or not account["AccountKey"]:
        return False, "sim_account_key_missing"
    return True, "sim_readonly_identity_verified"


def main() -> int:
    parser = argparse.ArgumentParser(description="Saxo simulation-only read-only preflight")
    parser.add_argument("--expected-account-id", default=os.getenv("SAXO_SIM_EXPECTED_ACCOUNT_ID", ""))
    args = parser.parse_args()
    try:
        ok, reason = check(SaxoSimClient(), expected_account_id=args.expected_account_id)
    except (SaxoSimError, ValueError, PermissionError):
        print("BLOCKED: Saxo simulation access not verified")
        return 2
    print(("PASS: " if ok else "BLOCKED: ") + reason)
    print("Saxo order submission and live trading remain disabled.")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
