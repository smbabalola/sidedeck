"""Opt-in, read-only Alpaca paper HTTP transport; never submits orders."""
from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from sidedeck.infrastructure.alpaca_paper import AlpacaPaperBinding

_ALLOWED = frozenset(("/v2/account", "/v2/positions"))


class PaperReadError(RuntimeError):
    pass


def make_paper_get(binding: AlpacaPaperBinding, *, timeout_seconds: float = 5.0):
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
        secret = os.environ.get(binding.api_secret_env)
        if not key or not secret:
            raise PaperReadError("SideDeck paper credentials unavailable")
        request = Request(
            binding.base_url.rstrip("/") + path,
            method="GET",
            headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret,
                     "Accept": "application/json"},
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                if response.status != 200:
                    raise PaperReadError("paper read returned unsuccessful status")
                data = response.read(2_000_001)
                if len(data) > 2_000_000:
                    raise PaperReadError("paper response exceeds size limit")
                return json.loads(data)
        except (HTTPError, URLError, ValueError, OSError) as exc:
            raise PaperReadError("paper read failed; check connectivity and access") from None
    return get
