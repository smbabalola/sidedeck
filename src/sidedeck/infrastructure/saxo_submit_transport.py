"""Saxo SIM POST transport, disabled unless explicitly constructed for review.

The application layer still keeps the network flag off. This transport has no
live host, no retry, no redirect and no response-body logging.
"""
from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from sidedeck.infrastructure.saxo_sim import SIM_BASE


class SaxoSimSubmitTransport:
    def __init__(self, *, enabled: bool = False, timeout_seconds: float = 10.0,
                 token_env: str = "SAXO_SIM_ACCESS_TOKEN") -> None:
        if timeout_seconds <= 0 or timeout_seconds > 30:
            raise ValueError("invalid Saxo SIM timeout")
        if token_env != "SAXO_SIM_ACCESS_TOKEN":
            raise ValueError("unexpected Saxo token variable")
        self._enabled = enabled
        self._timeout = timeout_seconds
        self._token_env = token_env

    @staticmethod
    def validate_payload(payload: dict[str, Any]) -> None:
        if set(payload) != {"AccountKey", "Uic", "AssetType", "BuySell", "Amount",
                            "OrderType", "OrderDuration", "ExternalReference"}:
            raise ValueError("Saxo SIM payload fields are not exact")
        if (not isinstance(payload["AccountKey"], str) or not payload["AccountKey"]
                or any(char.isspace() for char in payload["AccountKey"])):
            raise ValueError("invalid Saxo account key")
        if payload["Uic"] != 23241352 or payload["AssetType"] != "Stock":
            raise ValueError("payload is not the approved SOFI instrument")
        if payload["BuySell"] != "Buy" or payload["Amount"] != 1:
            raise ValueError("payload is not the approved one-share buy")
        if payload["OrderType"] != "Market" or payload["OrderDuration"] != {"DurationType": "DayOrder"}:
            raise ValueError("payload order type is not approved")
        reference = payload["ExternalReference"]
        if not isinstance(reference, str) or not 1 <= len(reference) <= 50:
            raise ValueError("invalid external reference")

    def submit(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.validate_payload(payload)
        if not self._enabled:
            raise RuntimeError("Saxo SIM POST transport is disabled")
        token = os.environ.get(self._token_env, "")
        if not token:
            raise RuntimeError("Saxo SIM token unavailable")
        request = Request(
            SIM_BASE + "/trade/v2/orders", data=json.dumps(payload).encode("utf-8"),
            method="POST", headers={"Authorization": "Bearer " + token,
                                      "Accept": "application/json",
                                      "Content-Type": "application/json"},
        )
        try:
            with build_opener(_NoRedirect()).open(request, timeout=self._timeout) as response:
                raw = response.read(200_001)
                if len(raw) > 200_000:
                    raise RuntimeError("Saxo SIM response too large")
                parsed = json.loads(raw)
        except HTTPError as exc:
            raise RuntimeError(f"Saxo SIM order HTTP {exc.code}") from None
        except (URLError, OSError, ValueError):
            raise RuntimeError("Saxo SIM order transport failed") from None
        if not isinstance(parsed, dict):
            raise RuntimeError("Saxo SIM order response malformed")
        return parsed


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req: Request, fp: Any, code: int,
                         msg: str, headers: Any, newurl: str) -> None:
        return None

