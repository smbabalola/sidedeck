"""SD-048 (C7) eToro DEMO order transport, implemented per SD-041 and LOCKED.

* Only documented Demo routes (``require_demo_route``); eToro Real and Agent Portfolio
  routes are refused before any I/O. Host is pinned to ``https://public-api.etoro.com``.
* Requires an active, owner-signed ``PilotRelease`` (C8) at construction and on every
  send, and enforces **the release's own signed caps** in a persistent ledger keyed by
  the release digest (independent of any caller-chosen pilot budget). Every order body
  must equal the signed intent (instrument, units, limit, leverage 1, long, limitIOC);
  closes must be full closes of the signed instrument.
* ``offline_simulation`` is a read-only ``False``, so the desk additionally demands the
  release and a policy matching the intent.
* **Development lock:** ``NETWORK_TRANSPORT_ENABLED = False``. Without an injected
  opener the constructor refuses; real ``urllib`` openers cannot be injected. Tests
  inject mock openers only. Enabling the network needs a reviewed commit plus a
  separate owner release.
* Writes send ``x-request-id = reference_id``; a reference may only be re-sent with
  the byte-identical body (and only within the signed caps). Reads use a fresh id.
* No redirects, no retries, 15 s timeout, 1 MB cap, honest User-Agent. On a **write**,
  any failure once I/O starts (timeouts, resets, protocol errors, 408/5xx, non-200,
  oversized or unreadable bodies, redirects) raises ``TransportOutcomeUnknown``; the
  desk then halts and never resubmits. 404 raises ``TransportNotFound``. Other errors
  are sanitized (classification, HTTP status, request id, CF-Ray only).
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import (
    HTTPRedirectHandler, OpenerDirector, ProxyHandler, Request, build_opener,
)

from sidedeck.application.sd036_etoro_demo_desk import (
    BrokerExecutionDisabled, TransportNotFound, TransportOutcomeUnknown,
)
from sidedeck.application.sd042_etoro_credential_roles import (
    DEMO_PAIR_NAMES, require_execution_credentials,
)
from sidedeck.application.sd046_etoro_demo_pilot import route_for
from sidedeck.application.sd048_pilot_release import PilotRelease
from sidedeck.domain.etoro_demo_orders import (
    DEMO_ELIGIBILITY_PATH, DEMO_OPEN_PATH, DEMO_ORDER_LOOKUP_PATH, MARKET_DATA_RATES_PATH,
    require_demo_route,
)

NETWORK_TRANSPORT_ENABLED = False   # development lock (owner instruction 2026-10-22)
# Release-bound unlock: the aborted SD-058 preflight is closed. None means locked.
# A future pilot requires a new separately reviewed and owner-authorized lock-lift commit.
UNLOCKED_PILOT_DIGEST: str | None = None
ETORO_HOST = "https://public-api.etoro.com"
USER_AGENT = "SideDeck/0.1 (eToro Demo pilot transport)"
MAX_RESPONSE_BYTES = 1_000_000
TIMEOUT_SECONDS = 15.0
_QUERY_KEYS = frozenset({"referenceId", "orderId"})
_HEADER_VALUE = re.compile(r"[\x21-\x7e]{1,512}")


class EtoroDemoTransportError(RuntimeError):
    def __init__(self, classification: str, *, http_status: int | None = None,
                 request_id: str | None = None, cf_ray: str | None = None) -> None:
        super().__init__(f"eToro Demo transport: {classification}"
                         + (f" (HTTP {http_status})" if http_status else ""))
        self.classification, self.http_status = classification, http_status
        self.request_id, self.cf_ray = request_id, cf_ray


class Opener(Protocol):
    def open(self, request: Request, timeout: float) -> Any: ...


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args: Any) -> None:
        raise EtoroDemoTransportError("REDIRECT_REFUSED")


def _classify(status: int) -> str:
    return {401: "AUTH_REJECTED", 403: "ACCESS_DENIED", 400: "VALIDATION_FAILED",
            429: "RATE_LIMITED"}.get(status, "UNEXPECTED_RESPONSE")


class _ReleaseLedger:
    """Persistent per-release route counters, capped by the signed intent."""

    def __init__(self, path: str, release: PilotRelease) -> None:
        if path.strip() in ("", ":memory:") or path.startswith("file:"):
            raise BrokerExecutionDisabled("the transport ledger must be a durable file")
        self._db = sqlite3.connect(Path(path), isolation_level=None)
        self._db.execute("CREATE TABLE IF NOT EXISTS sd048_transport_ledger (digest TEXT NOT "
                         "NULL, route TEXT NOT NULL, used INTEGER NOT NULL, "
                         "PRIMARY KEY (digest, route))")
        self._digest = release.digest
        self._caps = dict(release.intent.request_caps)

    def reserve(self, route: str) -> None:
        self._db.execute("BEGIN IMMEDIATE")
        try:
            row = self._db.execute("SELECT used FROM sd048_transport_ledger WHERE digest=? AND "
                                   "route=?", (self._digest, route)).fetchone()
            if (0 if row is None else int(row[0])) >= self._caps.get(route, 0):
                raise EtoroDemoTransportError("SIGNED_REQUEST_CAP_EXHAUSTED")
            self._db.execute("INSERT INTO sd048_transport_ledger VALUES (?, ?, 1) ON CONFLICT"
                             "(digest, route) DO UPDATE SET used = used + 1",
                             (self._digest, route))
            self._db.execute("COMMIT")
        except BaseException:
            if self._db.in_transaction:
                self._db.execute("ROLLBACK")
            raise

    def close(self) -> None:
        self._db.close()


class EtoroDemoHttpTransport:
    def __init__(self, *, api_key: str, user_key: str, release: PilotRelease, ledger_path: str,
                 opener: Opener | None = None) -> None:
        if not isinstance(release, PilotRelease):
            raise BrokerExecutionDisabled("a signed pilot release is required")
        release.require_active()
        for value in (api_key, user_key):
            if not isinstance(value, str) or not _HEADER_VALUE.fullmatch(value):
                raise ValueError("Demo credentials are missing or malformed")
        if isinstance(opener, OpenerDirector):
            raise BrokerExecutionDisabled("real urllib openers cannot be injected")
        active: Any = opener
        if active is None:
            if not network_transport_enabled(release.digest):
                raise BrokerExecutionDisabled("network transport is locked in this phase")
            active = build_opener(ProxyHandler({}), _NoRedirect())  # pragma: no cover
        self.__headers = {"x-api-key": api_key, "x-user-key": user_key}
        self._opener: Any = active
        self._release = release
        self._ledger = _ReleaseLedger(ledger_path, release)
        self._sent_bodies: dict[str, str] = {}

    @property
    def offline_simulation(self) -> bool:
        return False

    @classmethod
    def from_environment(cls, env: Mapping[str, str], *, release: PilotRelease,
                         ledger_path: str, opener: Opener | None = None
                         ) -> "EtoroDemoHttpTransport":
        require_execution_credentials(env)
        return cls(api_key=env[DEMO_PAIR_NAMES[0]].strip(),
                   user_key=env[DEMO_PAIR_NAMES[1]].strip(), release=release,
                   ledger_path=ledger_path, opener=opener)

    def __repr__(self) -> str:
        return "EtoroDemoHttpTransport(<credentials hidden>)"

    def close(self) -> None:
        self._ledger.close()

    def _require_signed_body(self, path: str, body: dict[str, Any]) -> None:
        intent = self._release.intent
        if path == DEMO_ELIGIBILITY_PATH:
            if body != {"instrumentIds": [intent.instrument_id], "currency": "USD"}:
                raise EtoroDemoTransportError("ELIGIBILITY_DIFFERS_FROM_SIGNED_INTENT")
            return
        if path == DEMO_OPEN_PATH:
            fixed = {"action": "open", "transaction": "buy",
                     "instrumentId": intent.instrument_id, "orderType": "limitIOC",
                     "units": float(intent.units), "leverage": 1, "orderCurrency": "usd"}
            limit = body.get("limitRate")
            if (set(body) != set(fixed) | {"limitRate"}
                    or any(body[k] != v for k, v in fixed.items())
                    or Decimal(repr(body["units"])) != intent.units
                    or type(limit) is not float
                    or not Decimal("0") < Decimal(repr(limit)) <= intent.max_limit_rate):
                raise EtoroDemoTransportError("BODY_DIFFERS_FROM_SIGNED_INTENT")
        elif body != {"InstrumentID": intent.instrument_id, "UnitsToDeduct": None}:
            raise EtoroDemoTransportError("CLOSE_DIFFERS_FROM_SIGNED_INTENT")

    def send(self, method: str, path: str, *, reference_id: str,
             body: dict[str, Any] | None = None, query: dict[str, str] | None = None) -> Any:
        require_demo_route(method, path)
        self._release.require_active()
        route, _shape = route_for(method, path)
        url = ETORO_HOST + path
        if path == MARKET_DATA_RATES_PATH:
            if query != {"instrumentIds": str(self._release.intent.instrument_id)}:
                raise EtoroDemoTransportError("QUERY_REFUSED")
            url += "?" + urlencode(query)
        elif query is not None:
            if path != DEMO_ORDER_LOOKUP_PATH or len(query) != 1 or not set(query) <= _QUERY_KEYS:
                raise EtoroDemoTransportError("QUERY_REFUSED")
            url += "?" + urlencode(query)
        headers = {**self.__headers, "User-Agent": USER_AGENT, "Accept": "application/json"}
        data: bytes | None = None
        write = method == "POST"
        if write:
            if body is None:
                raise EtoroDemoTransportError("BODY_REQUIRED")
            self._require_signed_body(path, body)
            data = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
            digest = hashlib.sha256(data).hexdigest()
            if self._sent_bodies.setdefault(reference_id, digest) != digest:
                raise EtoroDemoTransportError("REFERENCE_REUSED_WITH_DIFFERENT_BODY")
            request_id = reference_id
            headers["Content-Type"] = "application/json"
        else:
            if body is not None:
                raise EtoroDemoTransportError("BODY_NOT_ALLOWED")
            request_id = str(uuid.uuid4())
        headers["x-request-id"] = request_id
        request = Request(url, data=data, method=method, headers=headers)
        self._ledger.reserve(route)            # counted before any I/O, never refunded
        response: Any = None
        try:
            response = self._opener.open(request, timeout=TIMEOUT_SECONDS)
            status = int(response.status)
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if status != 200 or len(raw) > MAX_RESPONSE_BYTES:
                raise EtoroDemoTransportError("UNEXPECTED_RESPONSE", http_status=status,
                                              request_id=request_id)
            return json.loads(raw)
        except HTTPError as exc:
            cf_ray = exc.headers.get("CF-Ray") if exc.headers else None
            if exc.code == 404:
                raise TransportNotFound("eToro Demo order not found") from None
            if write and (exc.code >= 500 or exc.code == 408):
                raise TransportOutcomeUnknown(f"write outcome unknown (HTTP {exc.code})") from None
            raise EtoroDemoTransportError(_classify(exc.code), http_status=exc.code,
                                          request_id=request_id, cf_ray=cf_ray) from None
        except Exception as exc:
            if write:
                raise TransportOutcomeUnknown("write outcome unknown") from None
            if isinstance(exc, EtoroDemoTransportError):
                raise
            raise EtoroDemoTransportError("NETWORK_OR_PROTOCOL_ERROR",
                                          request_id=request_id) from None
        finally:
            closer = getattr(response, "close", None)
            if callable(closer):
                closer()


def network_transport_enabled(release_digest: str | None = None) -> bool:
    """Read-only view of the lock (callers must not assign it). True only for the single
    release digest named by the reviewed lock-lift commit (or the global lock, never set)."""
    if NETWORK_TRANSPORT_ENABLED is True:
        return True
    unlocked = UNLOCKED_PILOT_DIGEST
    return (isinstance(unlocked, str) and len(unlocked) == 64
            and isinstance(release_digest, str) and release_digest == unlocked)


class ProductionTransportFactory:
    """The single production construction path (used only by the SD-054 operator).
    ``validate`` has no side effects and runs before the single-use release is consumed.
    No opener is ever injected here."""

    def __init__(self, env: Mapping[str, str], release_digest: str) -> None:
        self.__env = dict(env)
        self._digest = release_digest

    def __repr__(self) -> str:
        return "ProductionTransportFactory(<credentials hidden>)"

    def validate(self) -> None:
        if not network_transport_enabled(self._digest):
            raise BrokerExecutionDisabled("network transport is locked in this phase")
        require_execution_credentials(self.__env)

    def __call__(self, release: PilotRelease, ledger_path: str) -> EtoroDemoHttpTransport:
        if release.digest != self._digest:
            raise BrokerExecutionDisabled("release differs from the unlocked pilot digest")
        self.validate()
        return EtoroDemoHttpTransport.from_environment(self.__env, release=release,
                                                       ledger_path=ledger_path)


def production_transport_factory(env: Mapping[str, str],
                                 release_digest: str) -> ProductionTransportFactory:
    return ProductionTransportFactory(env, release_digest)
