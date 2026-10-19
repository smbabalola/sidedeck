"""Strictly read-only Saxo simulation gateway connector.

No live environment, order submission, refresh token, or POST methods exist here.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

SIM_BASE = "https://gateway.saxobank.com/sim/openapi"
_ALLOWED = frozenset(("/port/v1/users/me", "/port/v1/accounts/me", "/port/v1/balances/me", "/port/v1/positions/me", "/port/v1/orders/me"))


class SaxoSimError(RuntimeError):
    """Redacted connection or response failure."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self, req: Request, fp: Any, code: int, msg: str, headers: Any, newurl: str,
    ) -> None:
        return None


@dataclass(frozen=True)
class SaxoSimClient:
    """Only Saxo SIM, only two account-discovery GET requests."""

    base_url: str = SIM_BASE
    token_env: str = "SAXO_SIM_ACCESS_TOKEN"
    timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        if self.base_url != SIM_BASE:
            raise ValueError("only Saxo simulation API is authorized")
        if self.token_env != "SAXO_SIM_ACCESS_TOKEN":
            raise ValueError("token must be read from SideDeck simulation environment")
        if not 0 < self.timeout_seconds <= 30:
            raise ValueError("invalid timeout")

    def get(self, path: str) -> dict[str, Any]:
        if path not in _ALLOWED:
            raise PermissionError("Saxo endpoint is not approved for read-only access")
        token = os.environ.get(self.token_env, "")
        if not token:
            raise SaxoSimError("Saxo SIM token unavailable")
        req = Request(
            self.base_url + path,
            method="GET",
            headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
        )
        try:
            with build_opener(_NoRedirect()).open(req, timeout=self.timeout_seconds) as response:
                if response.status != 200:
                    raise SaxoSimError("Saxo SIM read failed")
                raw = response.read(2_000_001)
                if len(raw) > 2_000_000:
                    raise SaxoSimError("Saxo SIM response too large")
                result = json.loads(raw)
        except HTTPError as exc:
            if exc.code in (401, 403):
                raise SaxoSimError("Saxo SIM authentication or access rejected") from None
            raise SaxoSimError("Saxo SIM HTTP request failed") from None
        except (URLError, OSError, ValueError):
            raise SaxoSimError("Saxo SIM response or connection failed") from None
        if not isinstance(result, dict):
            raise SaxoSimError("unexpected Saxo SIM response shape")
        return result

    def user(self) -> dict[str, Any]:
        return self.get("/port/v1/users/me")

    def accounts(self) -> dict[str, Any]:
        return self.get("/port/v1/accounts/me")

    def client_balance(self) -> dict[str, Any]:
        """Client-wide balance: never assume it belongs to a single account."""
        return self.get("/port/v1/balances/me")

    def client_positions(self) -> dict[str, Any]:
        """Client-wide positions, potentially paginated; no order execution."""
        return self.get("/port/v1/positions/me")

    def client_orders(self) -> dict[str, Any]:
        """Client-wide open orders, potentially paginated."""
        return self.get("/port/v1/orders/me")
