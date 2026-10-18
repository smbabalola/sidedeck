"""SideDeck-controlled, explicit-opt-in ALPACA PAPER account read only.

Never posts orders. Never contacts the live brokerage host, eToro or Yahoo.
Local private credentials must already be set in the process environment.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from http.client import HTTPMessage
import json
import os
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from sidedeck.domain.alpaca_paper import (
    MAX_PAYLOAD_BYTES, PAPER_HOST, AlpacaPaperReadClient, PaperGetTransport,
    validate_paper_get,
)


@dataclass(frozen=True)
class PaperCredentials:
    api_key: str = field(repr=False)
    secret_key: str = field(repr=False)

    @classmethod
    def from_environment(cls) -> "PaperCredentials":
        key = os.environ.get("ALPACA_API_KEY")
        names = ("ALPACA_SECRET_KEY", "ALPACA_API_SECRET_KEY", "APCA_API_SECRET_KEY")
        populated = [os.environ[name] for name in names if os.environ.get(name)]
        if not key or not populated:
            raise ValueError("ALPACA_API_KEY and a paper API secret variable are required")
        if any(candidate != populated[0] for candidate in populated):
            raise ValueError("conflicting paper secret variables")
        return cls(api_key=key, secret_key=populated[0])


class AlpacaPaperHttpTransport(PaperGetTransport):
    """Hard-coded paper host, GET-only allowlist, no redirects/retries."""

    def __init__(self, credentials: PaperCredentials) -> None:
        self._credentials = credentials

    def get(self, path: str, params: Mapping[str, str]) -> tuple[int, bytes]:
        validate_paper_get(path, params)
        url = f"{PAPER_HOST}{path}"
        if params:
            url += f"?{urlencode(params)}"
        request = Request(
            url, method="GET",
            headers={
                "APCA-API-KEY-ID": self._credentials.api_key,
                "APCA-API-SECRET-KEY": self._credentials.secret_key,
                "Accept": "application/json",
            },
        )
        try:
            with build_opener(_NoRedirects()).open(request, timeout=10) as response:
                return response.status, response.read(MAX_PAYLOAD_BYTES + 1)
        except HTTPError as exc:
            # Never return or log error bodies that could expose account details.
            exc.close()
            return exc.code, b""
        except URLError:
            raise RuntimeError("Alpaca PAPER transport unavailable") from None


class _NoRedirects(HTTPRedirectHandler):
    def redirect_request(
        self, req: Request, fp: Any, code: int, msg: str,
        headers: HTTPMessage, newurl: str,
    ) -> None:
        raise RuntimeError("Alpaca PAPER redirects are forbidden")


class _FixturePaperTransport(PaperGetTransport):
    """Synthetic values only; no credentials, sockets or broker integration."""

    def get(self, path: str, params: Mapping[str, str]) -> tuple[int, bytes]:
        validate_paper_get(path, params)
        examples: dict[str, object] = {
            "/v2/account": {
                "status": "ACTIVE", "cash": "1000", "equity": "1000",
                "buying_power": "1000", "multiplier": "1",
                "account_blocked": False, "trading_blocked": False,
            },
            "/v2/positions": [],
            "/v2/orders": [],
        }
        return 200, json.dumps(examples[path]).encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect Alpaca PAPER from SideDeck (no orders)")
    parser.add_argument("--dry-run", action="store_true", help="offline synthetic paper snapshot")
    parser.add_argument("--paper-only", action="store_true")
    parser.add_argument("--allow-read-network", action="store_true")
    parser.add_argument("--confirm-owner-paper-read-only", action="store_true")
    args = parser.parse_args()

    if args.dry_run:
        transport: PaperGetTransport = _FixturePaperTransport()
    else:
        if not (args.paper_only and args.allow_read_network and args.confirm_owner_paper_read_only):
            parser.error("requires --paper-only --allow-read-network --confirm-owner-paper-read-only")
        try:
            credentials = PaperCredentials.from_environment()
        except ValueError as exc:
            parser.error(str(exc))
        transport = AlpacaPaperHttpTransport(credentials)

    snapshot = AlpacaPaperReadClient(transport).inspect(observed_at=datetime.now(timezone.utc))
    # Never print an account ID, credential, raw provider JSON or HTTP headers.
    report = {
        "source": snapshot.source,
        "mode": "FIXTURE_NOT_REAL" if args.dry_run else "PAPER_ACCOUNT_READ_ONLY",
        "broker_scope": snapshot.broker_scope,
        "observed_at_utc": snapshot.observed_at.isoformat(),
        "account": asdict(snapshot.account),
        "positions": [asdict(position) for position in snapshot.positions],
        "open_orders": [asdict(order) for order in snapshot.open_orders],
        "order_submission_enabled": False,
        "two_broker_accounts_verified": False,
    }
    print(json.dumps(report, default=str, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
