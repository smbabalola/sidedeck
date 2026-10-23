"""Opt-in, read-only Alpaca paper HTTP transport; never submits orders."""
from __future__ import annotations

import json
import os
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from sidedeck.infrastructure.alpaca_paper import AlpacaPaperBinding

_ALLOWED = frozenset(("/v2/account", "/v2/positions", "/v2/orders?status=open&limit=500"))
# Slot-B secret may also be stored as ALPACA_API_SECRET2 (the name SD-035 and the
# owner's local .env use). Slot A's ALPACA_API_SECRET is never an alias here.
_SECRET_ALIASES = {"ALPACA_API_SECRET_KEY2": ("ALPACA_API_SECRET_KEY2", "ALPACA_API_SECRET2")}


def _paper_secret(binding_secret_env: str) -> str | None:
    names = _SECRET_ALIASES.get(binding_secret_env, (binding_secret_env,))
    values = [os.environ[name] for name in names if os.environ.get(name)]
    if any(value != values[0] for value in values):
        raise PaperReadError("conflicting SideDeck paper secret variables")
    return values[0] if values else None


class PaperReadError(RuntimeError):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req: Request, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


def make_paper_get(binding: AlpacaPaperBinding, *, timeout_seconds: float = 5.0) -> Callable[[str], Any]:
    """Create a GET-only callable. No requests occur until explicitly invoked.

    Credentials are loaded from the SideDeck-specific environment variable names
    at call time; they must never be printed or persisted.
    """
    if binding.enabled:
        raise ValueError("broker order execution must remain disabled")
    if timeout_seconds <= 0 or timeout_seconds > 30:
        raise ValueError("invalid timeout")
    def get(path: str) -> Any:
        if path not in _ALLOWED:
            raise PermissionError("endpoint not permitted for paper read-only transport")
        key = os.environ.get(binding.api_key_env)
        secret = _paper_secret(binding.api_secret_env)
        if not key or not secret:
            raise PaperReadError("SideDeck paper credentials unavailable")
        request = Request(
            binding.base_url.rstrip("/") + path,
            method="GET",
            headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret,
                     "Accept": "application/json"},
        )
        try:
            with build_opener(_NoRedirect()).open(request, timeout=timeout_seconds) as response:
                if response.status != 200:
                    raise PaperReadError("paper read returned unsuccessful status")
                data = response.read(2_000_001)
                if len(data) > 2_000_000:
                    raise PaperReadError("paper response exceeds size limit")
                return json.loads(data)
        except (HTTPError, URLError, ValueError, OSError):
            raise PaperReadError("paper read failed; check connectivity and access") from None
    return get
