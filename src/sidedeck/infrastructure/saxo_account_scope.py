"""Allowlisted account-scoped GET paths for Saxo SIM.

No client-controlled URL, arbitrary endpoint, order submission, or redirects.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from sidedeck.infrastructure.saxo_sim import SaxoSimClient


@dataclass(frozen=True)
class SaxoAccountScope:
    account_id: str
    account_key: str
    client_key: str

    def __post_init__(self) -> None:
        for value in (self.account_id, self.account_key, self.client_key):
            if not value or len(value) > 256 or any(c.isspace() for c in value):
                raise ValueError("invalid Saxo account reference")


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
    return SaxoAccountScope(expected_account_id, matches[0]["AccountKey"], client_key)


def _path(kind: str, scope: SaxoAccountScope) -> str:
    if kind not in {"balances", "positions", "orders"}:
        raise PermissionError("unapproved Saxo read")
    ck = quote(scope.client_key, safe="")
    ak = quote(scope.account_key, safe="")
    return f"/port/v1/{kind}?ClientKey={ck}&AccountKey={ak}"


def scoped_get(client: SaxoSimClient, kind: str, scope: SaxoAccountScope) -> dict[str, Any]:
    """Read account-scoped balance/positions/orders, no orders submitted."""
    return client.get(_path(kind, scope))
