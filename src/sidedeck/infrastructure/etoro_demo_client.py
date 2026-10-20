"""Read-only eToro DEMO portfolio client: one allowlisted GET, nothing else.

* Exact host ``https://public-api.etoro.com`` and exact path
  ``/api/v1/trading/info/demo/pnl``; every other path (including the real
  account) raises ``PermissionError`` before any network activity.
* GET only. No POST/PUT/DELETE capability exists in this module.
* No redirects, no retries, bounded response size, 15 s timeout.
* Honest ``SideDeck/0.1`` User-Agent; no browser impersonation or Cloudflare
  workarounds. Cloudflare 1010 is reported with its Ray ID and stops.
* Keys are held privately, never logged, and never appear in repr or errors.
Tests drive it with a fake opener; it is never run in CI.
"""
from __future__ import annotations

import json
import uuid
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

ETORO_HOST = "https://public-api.etoro.com"
DEMO_PORTFOLIO_PATH = "/api/v1/trading/info/demo/pnl"
ALLOWED_PATHS = frozenset({DEMO_PORTFOLIO_PATH})
USER_AGENT = "SideDeck/0.1 (read-only demo portfolio)"
MAX_RESPONSE_BYTES = 5_000_000
TIMEOUT_SECONDS = 15.0


class EtoroDemoAccessError(RuntimeError):
    """Sanitised failure: classification, HTTP status and Cloudflare Ray ID only."""

    def __init__(self, classification: str, *, http_status: int | None = None,
                 cf_ray: str | None = None, request_id: str | None = None) -> None:
        super().__init__(f"eToro Demo read failed: {classification}"
                         + (f" (HTTP {http_status})" if http_status else ""))
        self.classification = classification
        self.http_status = http_status
        self.cf_ray = cf_ray
        self.request_id = request_id


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args: Any) -> None:
        raise EtoroDemoAccessError("REDIRECT_REFUSED")


def _classify(status: int, body: bytes) -> str:
    if status == 401:
        return "AUTH_REJECTED"
    if status == 403:
        text = body[:2000].decode("utf-8", "replace")
        return "CLOUDFLARE_1010" if "1010" in text else "ACCESS_DENIED"
    if status == 404:
        return "ENDPOINT_NOT_FOUND"
    if status == 429:
        return "RATE_LIMITED"
    return "UNEXPECTED_RESPONSE"


class EtoroDemoReadClient:
    def __init__(self, *, api_key: str, user_key: str) -> None:
        if not api_key or not user_key:
            raise ValueError("ETORO_API_KEY and ETORO_USER_KEY are required")
        self.__headers = {"x-api-key": api_key, "x-user-key": user_key}

    def __repr__(self) -> str:
        return "EtoroDemoReadClient(<credentials hidden>)"

    def _get(self, path: str) -> tuple[Any, str]:
        if path not in ALLOWED_PATHS:
            raise PermissionError("eToro endpoint is not approved for read-only Demo access")
        request_id = str(uuid.uuid4())
        request = Request(ETORO_HOST + path, method="GET", headers={
            **self.__headers, "x-request-id": request_id, "User-Agent": USER_AGENT,
            "Accept": "application/json"})
        try:
            with build_opener(_NoRedirect()).open(request, timeout=TIMEOUT_SECONDS) as response:
                status, raw = response.status, response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            body = exc.read(2000) if exc.fp is not None else b""
            cf_ray = exc.headers.get("CF-Ray") if exc.headers else None
            raise EtoroDemoAccessError(_classify(exc.code, body), http_status=exc.code,
                                       cf_ray=cf_ray, request_id=request_id) from None
        except (URLError, OSError):
            raise EtoroDemoAccessError("NETWORK_ERROR", request_id=request_id) from None
        if status != 200:
            raise EtoroDemoAccessError(_classify(status, raw), http_status=status,
                                       request_id=request_id)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise EtoroDemoAccessError("RESPONSE_TOO_LARGE", http_status=status,
                                       request_id=request_id)
        try:
            return json.loads(raw), request_id
        except ValueError:
            raise EtoroDemoAccessError("MALFORMED_JSON", http_status=status,
                                       request_id=request_id) from None

    def read_demo_portfolio(self) -> tuple[Any, str]:
        """One GET of the Demo portfolio; returns (payload, request_id)."""
        return self._get(DEMO_PORTFOLIO_PATH)
