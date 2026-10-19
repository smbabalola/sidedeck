"""Strictly read-only Saxo simulation gateway connector.

No live environment, order submission, refresh token, or POST methods exist here.
"""
from __future__ import annotations

import json
import os
import re
from urllib.parse import parse_qs, urlsplit
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


def _is_audit_path(path: str) -> bool:
    parsed = urlsplit(path)
    if parsed.scheme or parsed.netloc or parsed.fragment or parsed.path != "/cs/v1/audit/orderactivities":
        return False
    query = parse_qs(parsed.query, keep_blank_values=True)
    required = {"AccountKey", "ClientKey", "EntryType", "IncludeSubAccounts", "$top"}
    if not required.issubset(query) or set(query) - required - {"OrderId", "$skip"}:
        return False
    if any(len(query[key]) != 1 or not query[key][0] for key in ("AccountKey", "ClientKey")):
        return False
    if query["EntryType"] != ["All"] or query["IncludeSubAccounts"] != ["false"]:
        return False
    if query["$top"] != ["100"]:
        return False
    if "$skip" in query and (len(query["$skip"]) != 1 or not re.fullmatch(r"[0-9]+", query["$skip"][0])):
        return False
    if "OrderId" in query and (len(query["OrderId"]) != 1 or not query["OrderId"][0]):
        return False
    return True


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
        scoped = re.fullmatch(r"/port/v1/(balances|positions|orders)[?]ClientKey=[A-Za-z0-9%_-]+&AccountKey=[A-Za-z0-9%_-]+", path)
        lookup = re.fullmatch(r"/ref/v1/instruments[?]AccountKey=[A-Za-z0-9%_-]+&AssetTypes=Stock&Keywords=[A-Z]{1,6}&%24top=20", path)
        detail = re.fullmatch(r"/ref/v1/instruments/details/[1-9][0-9]*/Stock[?]AccountKey=[A-Za-z0-9%_-]+&ClientKey=[A-Za-z0-9%_-]+", path)
        price = re.fullmatch(r"/trade/v1/infoprices[?]AccountKey=[A-Za-z0-9%_-]+&AssetType=Stock&Uic=[1-9][0-9]*", path)
        audit = _is_audit_path(path)
        if path not in _ALLOWED and all(item is None or item is False for item in (scoped, lookup, detail, price, audit)):
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
            raise SaxoSimError(f"Saxo SIM HTTP {exc.code}") from None
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
