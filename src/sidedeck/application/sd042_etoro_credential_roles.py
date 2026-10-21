"""SD-042 eToro Demo credential-role separation (offline policy; no network, no values out).

Monitoring reads and approved execution must use *different* Demo credentials:

* monitoring: ``ETORO_API_KEY`` / ``ETORO_USER_KEY`` (target: Demo, Read-only);
* execution:  ``ETORO_DEMO_TRADE_API_KEY`` / ``ETORO_DEMO_TRADE_USER_KEY`` (Demo, Read/Write),
  used only by a future, separately released and approved execution path.

The user key identifies the account permission; the public API key identifies
the application and may legitimately be shared, so separation means distinct
user keys. The owner confirmed on 2026-10-21 that the current monitoring key is
Demo with Read/Write permission (risk R9). This module reports role status only;
it never returns, logs or hashes credential values, and it grants nothing:
execution release remains ``NO_GO`` regardless of the result.
"""
from __future__ import annotations

import hmac
from collections.abc import Mapping
from typing import Any

MONITOR_NAMES = ("ETORO_API_KEY", "ETORO_USER_KEY")
EXECUTION_NAMES = ("ETORO_DEMO_TRADE_API_KEY", "ETORO_DEMO_TRADE_USER_KEY")
OWNER_RECORDED_MONITOR_KEY = {"environment": "DEMO", "permission": "READ_WRITE",
                              "confirmed": "2026-10-21",
                              "ip_whitelist": "UNVERIFIED", "expiry": "UNVERIFIED"}


class CredentialRoleError(PermissionError):
    """Credential roles are not separated; no execution credential may be used."""


def _present(env: Mapping[str, str], names: tuple[str, str]) -> bool:
    return all(bool(env.get(name, "").strip()) for name in names)


def assess_roles(env: Mapping[str, str]) -> dict[str, Any]:
    """Sanitized role status. Never includes values, lengths or hashes."""
    monitor = _present(env, MONITOR_NAMES)
    execution = _present(env, EXECUTION_NAMES)
    if not execution:
        separation = "EXECUTION_CREDENTIAL_NOT_CONFIGURED"
    elif not monitor:
        separation = "MONITOR_CREDENTIAL_NOT_CONFIGURED"
    elif hmac.compare_digest(env[MONITOR_NAMES[1]].strip().encode(),
                             env[EXECUTION_NAMES[1]].strip().encode()):
        separation = "SHARED_REFUSED"
    else:
        separation = "SEPARATED_PERMISSIONS_UNVERIFIED"
    warnings = []
    if OWNER_RECORDED_MONITOR_KEY["permission"] != "READ_ONLY":
        warnings.append("R9_MONITORING_KEY_IS_READ_WRITE")
    return {"monitor_credential": "PRESENT" if monitor else "ABSENT",
            "execution_credential": "PRESENT" if execution else "ABSENT",
            "separation": separation,
            "monitor_key_owner_record": dict(OWNER_RECORDED_MONITOR_KEY),
            "warnings": warnings, "execution_release": "NO_GO"}


def require_separated_execution_credentials(env: Mapping[str, str]) -> None:
    """Gate for any future execution path: refuses unless roles are distinct."""
    status = assess_roles(env)["separation"]
    if status != "SEPARATED_PERMISSIONS_UNVERIFIED":
        raise CredentialRoleError(f"execution credentials refused: {status}")
