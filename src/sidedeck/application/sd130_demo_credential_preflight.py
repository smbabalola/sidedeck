"""SD-130 local eToro Demo .env preflight — NO NETWORK, NO ORDERS.

Safely reports *credential NAMES/roles* and development release locks, never
values, lengths, digests, portfolio information, or account identifiers.
This diagnostic cannot establish the account's actual Demo/Write entitlements.
It must never be used to unlock trading or approve a broker request.
"""
from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sidedeck.application.sd042_etoro_credential_roles import (
    DEMO_PAIR_NAMES, LEGACY_NAMES, POLICY, assess_roles,
)
from sidedeck.application.sd050_msft_instrument_lookup import load_local_credentials
from sidedeck.application.sd107_demo_gateway import BROKER_ROUTES

_RELEVANT = DEMO_PAIR_NAMES + LEGACY_NAMES


def local_demo_preflight(
    env_file: str, *, inherited: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Check local keys and process environment without using any API client."""
    filename = Path(env_file)
    if filename.is_symlink():
        raise ValueError("credential file must not be a symlink")
    if not filename.is_file():
        # Missing file is an actionable blocker, not implied empty entitlements.
        return {
            "schema": "sidedeck-demo-credential-preflight/1",
            "credential_config": "MISSING_LOCAL_ENV_FILE",
            "demo_pair": "UNVERIFIED", "legacy_names": "UNVERIFIED",
            "process_collision": "NOT_ASSESSED",
            "demo_write_entitlement": "UNVERIFIED",
            "broker_route": BROKER_ROUTES.get("ETORO_DEMO", "NOT_RELEASED"),
            "real_execution": "PERMANENTLY_EXCLUDED",
            "authenticated_requests": 0, "orders": 0,
        }
    source = load_local_credentials(str(filename))
    inherited_vars = os.environ if inherited is None else inherited
    session = {name: inherited_vars.get(name, "") for name in _RELEVANT}
    collision = any(
        source.get(name, "") and session.get(name, "") and
        source[name] != session[name] for name in _RELEVANT
    )
    combined = dict(session)
    combined.update(source)
    assessment = assess_roles(combined)
    status = ("FILE_PROCESS_VALUE_CONFLICT" if collision else assessment["status"])
    return {
        "schema": "sidedeck-demo-credential-preflight/1",
        "credential_config": status,
        "demo_pair": assessment["demo_pair"],
        "legacy_names": assessment["legacy_names"],
        "process_collision": "REFUSED" if collision else "NONE",
        "demo_write_entitlement": "UNVERIFIED",
        "broker_route": BROKER_ROUTES.get("ETORO_DEMO", "NOT_RELEASED"),
        "real_execution": "PERMANENTLY_EXCLUDED",
        "authenticated_requests": 0, "orders": 0,
        "next_action": (
            "Remove inherited or file-based legacy duplicate names; do not create another key."
            if assessment["legacy_names"] == "PRESENT" else
            "Resolve conflicting process and file values locally, without showing keys."
            if collision else
            "Verify Demo read/write entitlement separately under a scoped owner authorization."
            if status == POLICY else
            "Configure one reviewed eToro Demo read/write pair in the local parent .env."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check local eToro Demo credential ROLE setup, without broker access")
    parser.add_argument("--env-file", required=True, help="path to local parent-project .env")
    args = parser.parse_args(argv)
    try:
        report = local_demo_preflight(args.env_file)
    except (OSError, ValueError) as exc:
        # Exceptions must not include path, tokens or line contents.
        report = {"schema": "sidedeck-demo-credential-preflight/1",
                  "credential_config": "REFUSED_LOCAL_INPUT",
                  "reason": type(exc).__name__, "authenticated_requests": 0, "orders": 0}
    print(json.dumps(report, sort_keys=True))
    return 0 if report.get("credential_config") == POLICY else 2


if __name__ == "__main__":
    raise SystemExit(main())
