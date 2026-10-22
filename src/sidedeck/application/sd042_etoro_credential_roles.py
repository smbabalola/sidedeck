"""SD-042 eToro Demo credential policy (offline; no network, never outputs values).

Owner decision 2026-10-22 (ADR-004): **one** eToro Demo Read/Write credential pair,
``ETORO_DEMO_TRADE_API_KEY`` / ``ETORO_DEMO_TRADE_USER_KEY``, serves both portfolio
monitoring and any future, separately approved Demo execution. No second key and
no Real key. Risk R9 (a monitoring component holds a write-capable credential) is
explicitly owner-accepted for the Demo-only pilot, with compensating controls:

* monitoring uses only ``EtoroDemoReadClient`` (single ``/pnl`` GET path, no write
  methods; guarded by SD-041 tests);
* every order needs a signed owner approval (SD-033/SD-045), a persistent request
  budget, verified lineage, the protected baseline, the kill-switch and the Demo
  route allowlist; eToro Real routes are permanently refused;
* execution release stays ``NO_GO``; this module grants nothing.

The legacy names ``ETORO_API_KEY`` / ``ETORO_USER_KEY`` must not also be set: a
duplicate copy of the secret, or a second unknown pair, is refused rather than
guessed between.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

DEMO_PAIR_NAMES = ("ETORO_DEMO_TRADE_API_KEY", "ETORO_DEMO_TRADE_USER_KEY")
LEGACY_NAMES = ("ETORO_API_KEY", "ETORO_USER_KEY")
POLICY = "SINGLE_DEMO_PAIR_OWNER_ACCEPTED"
POLICY_DECIDED = "2026-10-22"
ACCEPTED_RISKS = ("R9_SHARED_DEMO_READ_WRITE_PAIR_OWNER_ACCEPTED",)
COMPENSATING_CONTROLS = ("MONITORING_GET_ONLY_SINGLE_PATH", "SIGNED_APPROVAL_PER_ORDER",
                         "PERSISTENT_REQUEST_BUDGETS", "VERIFIED_POSITION_LINEAGE",
                         "PROTECTED_BASELINE", "KILL_SWITCH", "DEMO_ROUTE_ALLOWLIST",
                         "REAL_ROUTES_PERMANENTLY_REFUSED")
OWNER_RECORDED_KEY = {"environment": "DEMO", "permission": "READ_WRITE",
                      "confirmed": "2026-10-21", "ip_whitelist": "OWNER_ATTESTED",
                      "expiry": "OWNER_ATTESTED"}


class CredentialRoleError(PermissionError):
    """The Demo credential configuration is missing or ambiguous; nothing may use it."""


def _present(env: Mapping[str, str], name: str) -> bool:
    return bool(env.get(name, "").strip())


def assess_roles(env: Mapping[str, str]) -> dict[str, Any]:
    """Sanitized policy status. Never includes values, lengths or hashes."""
    pair = all(_present(env, name) for name in DEMO_PAIR_NAMES)
    legacy = any(_present(env, name) for name in LEGACY_NAMES)
    if not pair:
        status = "DEMO_CREDENTIAL_NOT_CONFIGURED"
    elif legacy:
        status = "EXTRA_CREDENTIAL_NAMES_REFUSED"
    else:
        status = POLICY
    return {"policy": POLICY, "decided": POLICY_DECIDED, "status": status,
            "demo_pair": "PRESENT" if pair else "ABSENT",
            "legacy_names": "PRESENT" if legacy else "ABSENT",
            "owner_key_record": dict(OWNER_RECORDED_KEY),
            "accepted_risks": list(ACCEPTED_RISKS),
            "compensating_controls": list(COMPENSATING_CONTROLS),
            "execution_release": "NO_GO"}


def _require(env: Mapping[str, str]) -> tuple[str, str]:
    status = assess_roles(env)["status"]
    if status != POLICY:
        raise CredentialRoleError(f"eToro Demo credentials refused: {status}")
    return env[DEMO_PAIR_NAMES[0]].strip(), env[DEMO_PAIR_NAMES[1]].strip()


def monitoring_credentials(env: Mapping[str, str]) -> tuple[str, str]:
    """The pair for GET-only monitoring (pass only to ``EtoroDemoReadClient``)."""
    return _require(env)


def require_execution_credentials(env: Mapping[str, str]) -> None:
    """Gate for a future, separately released execution path. Grants no release."""
    _require(env)
