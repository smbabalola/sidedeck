"""Allowlisted account-scoped GET paths for Saxo SIM.

No client-controlled URL, arbitrary endpoint, order submission, or redirects.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

from sidedeck.infrastructure.saxo_sim import SaxoSimClient

# Process-local key: only verified_scope() in this process can mark a scope as
# derived from authenticated SIM user/account responses.
_SCOPE_SEAL_KEY = secrets.token_bytes(32)


def _scope_mac(account_id: str, account_key: str, client_key: str) -> str:
    material = "".join((account_id, account_key, client_key)).encode("utf-8")
    return hmac.new(_SCOPE_SEAL_KEY, material, hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class SaxoAccountScope:
    account_id: str
    account_key: str
    client_key: str
    verification_seal: str = field(default="", repr=False, compare=False)

    def __post_init__(self) -> None:
        for value in (self.account_id, self.account_key, self.client_key):
            if not value or len(value) > 256 or any(c.isspace() for c in value):
                raise ValueError("invalid Saxo account reference")

    def is_authenticated(self) -> bool:
        """True only for a scope returned by verified_scope() in this process."""
        if not self.verification_seal:
            return False
        expected = _scope_mac(self.account_id, self.account_key, self.client_key)
        return hmac.compare_digest(expected, self.verification_seal)


def verified_scope(client: SaxoSimClient, expected_account_id: str) -> SaxoAccountScope:
    """Derive opaque identifiers from authenticated SIM account and user responses."""
    if not expected_account_id.strip():
        raise ValueError("expected account identity missing")
    user = client.user()
    client_key = user.get("ClientKey")
    accounts = client.accounts()
    data = accounts.get("Data")
    if not isinstance(data, list) or not isinstance(client_key, str) or not client_key:
        raise ValueError("client/account response invalid")
    matches = [a for a in data if isinstance(a, dict)
               and a.get("AccountId") == expected_account_id and a.get("Active") is True]
    if len(matches) != 1 or not isinstance(matches[0].get("AccountKey"), str):
        raise ValueError("account identity unverified")
    account_key = matches[0]["AccountKey"]
    return SaxoAccountScope(expected_account_id, account_key, client_key,
                            verification_seal=_scope_mac(expected_account_id, account_key, client_key))


def _path(kind: str, scope: SaxoAccountScope) -> str:
    if kind not in {"balances", "positions", "orders"}:
        raise PermissionError("unapproved Saxo read")
    ck = quote(scope.client_key, safe="")
    ak = quote(scope.account_key, safe="")
    return f"/port/v1/{kind}?ClientKey={ck}&AccountKey={ak}"


def scoped_get(client: SaxoSimClient, kind: str, scope: SaxoAccountScope) -> dict[str, Any]:
    """Read account-scoped balance/positions/orders, no orders submitted."""
    return client.get(_path(kind, scope))
