"""SD-052 launcher: the single owner-authorized MSFT instrument lookup.

Usage (from the repository root)::

    .venv\\Scripts\\python.exe -m sidedeck.application.sd052_msft_lookup_cli --confirm-sd052

Scope is fixed in code: authorization ``SD-052``, ledger ``data/sd052-auth-budget.sqlite3``,
evidence ``data/sd052-msft-instrument.json``. The only option is the confirmation flag;
no option or environment variable selects another id, ledger, endpoint or retry.

Locks:
* ``sd050_msft_instrument_lookup.LOOKUP_NETWORK_ENABLED`` (False in source) is set True
  **only in this process** for the one ``run_once`` call, and restored to False in a
  ``finally`` block, also on error. Nothing on disk changes.
* The order transport lock (``NETWORK_TRANSPORT_ENABLED``) is never imported or
  referenced here; the SD-041 guard test enforces that no ``src`` module touches it.

The single attempt is reserved durably in the ledger before sending, so a second run
(or a crash after reservation) is refused by ``run_once``. No retry, no redirect.
"""
from __future__ import annotations

import argparse
import json
import os
from typing import Any

from sidedeck.application import sd050_msft_instrument_lookup as lookup
from sidedeck.application.sd042_etoro_credential_roles import DEMO_PAIR_NAMES, LEGACY_NAMES

AUTHORIZATION_ID = "SD-052"
EVIDENCE_PATH = str(lookup.DATA_DIR / "sd052-msft-instrument.json")
BASELINE_DB = str(lookup.DATA_DIR / "etoro_demo.sqlite3")


class LauncherRefused(RuntimeError):
    """A launcher precondition failed; nothing was sent."""


def _preconditions() -> str:
    if lookup.LOOKUP_NETWORK_ENABLED is not False:
        raise LauncherRefused("lookup network lock is not engaged in source")
    if AUTHORIZATION_ID not in lookup.AUTHORIZED_LOOKUP_IDS:
        raise LauncherRefused(f"{AUTHORIZATION_ID} is not an open authorization in code")
    if AUTHORIZATION_ID in lookup.EXHAUSTED_LOOKUP_IDS:
        raise LauncherRefused(f"{AUTHORIZATION_ID} is exhausted")
    budget = lookup.budget_path_for(AUTHORIZATION_ID)
    if lookup.attempts_consumed(budget) != 0:
        raise LauncherRefused(f"{AUTHORIZATION_ID} attempt already consumed")
    if lookup.attempts_consumed(lookup.budget_path_for("SD-050")) != 1:
        raise LauncherRefused("SD-050 ledger is not in its exhausted state")
    return budget


def run(env: dict[str, str]) -> dict[str, Any]:
    budget = _preconditions()
    lookup.LOOKUP_NETWORK_ENABLED = True          # in-process only, for this one call
    try:
        return lookup.run_once(env=env, db_path=BASELINE_DB, budget_path=budget,
                               evidence_path=EVIDENCE_PATH, authorization_id=AUTHORIZATION_ID)
    finally:
        lookup.LOOKUP_NETWORK_ENABLED = False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SD-052 one-shot MSFT eToro instrument lookup")
    parser.add_argument("--confirm-sd052", action="store_true", required=True)
    parser.parse_args(argv)
    env = {**{k: v for k, v in os.environ.items() if k in DEMO_PAIR_NAMES + LEGACY_NAMES},
           **lookup.load_local_credentials(str(lookup.DATA_DIR.parent / ".env"))}
    try:
        result = run(env)
    except Exception as exc:     # see sd052_attempts_consumed for whether anything was sent
        result = {"authorization": AUTHORIZATION_ID, "status": "NOT_RESOLVED",
                  "reason": type(exc).__name__ + ": " + str(exc)}
    result["lookup_network_locked_after"] = lookup.LOOKUP_NETWORK_ENABLED is False
    result["sd052_attempts_consumed"] = lookup.attempts_consumed(
        lookup.budget_path_for(AUTHORIZATION_ID))
    print(json.dumps(result, indent=2))
    return 0 if str(result.get("status", "")).startswith("RESOLVED") else 1


if __name__ == "__main__":
    raise SystemExit(main())
