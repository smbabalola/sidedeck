"""Explicitly opt-in, market-data-only eToro probe.

This command is intentionally inert unless both owner-confirmation flags are
provided. It is not used by tests and has no order, portfolio or broker-write
capability.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, time, timedelta, timezone
from http.client import HTTPMessage
import json
import os
from typing import Any, Mapping
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID

from sidedeck.domain.etoro import (
    ETORO_BASE_URL,
    _validate_path,
    EtoroHistoricalDataClient,
    MarketDataReadCapability,
    ReadOnlyMarketDataTransport,
)

MAX_RESPONSE_BYTES = 2_000_000


class UrllibReadOnlyTransport(ReadOnlyMarketDataTransport):
    def __init__(self, headers: Mapping[str, str]) -> None:
        self._headers = dict(headers)

    def get(self, path: str, params: Mapping[str, str], request_id: UUID) -> tuple[int, Mapping[str, str], bytes]:
        _validate_path(path)
        url = f"{ETORO_BASE_URL}{path}"
        if params:
            url = f"{url}?{urlencode(params)}"
        request = Request(url, headers={**self._headers, "x-request-id": str(request_id), "Accept": "application/json"}, method="GET")
        opener = build_opener(_NoRedirectHandler())
        try:
            with opener.open(request, timeout=10) as response:
                return response.status, dict(response.headers.items()), response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            body = exc.read(MAX_RESPONSE_BYTES + 1)
            return exc.code, dict(exc.headers.items()), body
        except URLError as exc:
            raise RuntimeError("eToro market-data transport failed") from exc


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, request: Request, fp: Any, code: int, msg: str, headers: HTTPMessage, newurl: str) -> None:
        raise RuntimeError("redirects are not allowed for credential-bearing market-data GETs")


class _DryRunTransport(ReadOnlyMarketDataTransport):
    """Published-shape local fixture; it never opens a socket."""

    ids = {"AAPL": 1001, "MSFT": 1002, "SPY": 1003, "QQQ": 1004}
    asset_types = {"AAPL": "EQUITY", "MSFT": "EQUITY", "SPY": "ETF", "QQQ": "ETF"}

    def get(self, path: str, params: Mapping[str, str], request_id: UUID) -> tuple[int, Mapping[str, str], bytes]:
        if path == "/api/v2/market-data/instruments/search":
            ticker = params["query"]
            payload: dict[str, Any] = {"results": [{"instrumentId": self.ids[ticker], "symbol": ticker, "type": "etf" if self.asset_types[ticker] == "ETF" else "stock", "exchangeId": "FIXTURE", "currency": "USD", "isLeveraged": False, "isInverse": False}]}
        else:
            instrument_id = int(path.split("/instruments/")[1].split("/")[0])
            payload = {"interval": "OneDay", "candles": [{"instrumentId": instrument_id, "candles": [{"instrumentID": instrument_id, "fromDate": "2026-01-05T21:00:00Z", "open": 100, "high": 105, "low": 99, "close": 102, "volume": 0.0}]}]}
        return 200, {}, json.dumps(payload).encode()


def completed_daily_cutoff(now: datetime) -> datetime:
    """Conservatively exclude the current UTC date and its forming daily bars."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("live probe clock must be timezone-aware")
    previous_day = now.astimezone(timezone.utc).date() - timedelta(days=1)
    return datetime.combine(previous_day, time.max, tzinfo=timezone.utc)


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only eToro historical market-data probe")
    parser.add_argument("--provider", choices=("etoro",), required=True)
    parser.add_argument("--market-data-only", action="store_true")
    parser.add_argument("--allow-read-network", action="store_true")
    parser.add_argument("--confirm-owner-read-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="use published-shape local fixtures; never opens a socket")
    parser.add_argument("--single-v2-search", choices=("AAPL",), help="one bounded read-only v2 search; no candles or other symbols")
    args = parser.parse_args()
    if not args.dry_run and (not args.market_data_only or not args.allow_read_network or not args.confirm_owner_read_only):
        parser.error("requires --market-data-only --allow-read-network --confirm-owner-read-only")
    if args.dry_run:
        transport: ReadOnlyMarketDataTransport = _DryRunTransport()
    else:
        api_key = os.environ.get("ETORO_API_KEY")
        user_key = os.environ.get("ETORO_USER_KEY")
        if not api_key or not user_key:
            parser.error("ETORO_API_KEY and ETORO_USER_KEY are required only after owner approval")
        transport = UrllibReadOnlyTransport({"x-api-key": api_key, "x-user-key": user_key})
    if args.single_v2_search:
        client = EtoroHistoricalDataClient(transport, capability=MarketDataReadCapability(), max_retries=0)
    else:
        client = EtoroHistoricalDataClient(transport, capability=MarketDataReadCapability())
    if args.single_v2_search:
        resolved = client.resolve_instrument(args.single_v2_search)
        print(json.dumps({"mode": "dry-run" if args.dry_run else "live-read-only", "kind": "v2-search-only", "ticker": resolved.ticker, "instrument_id": resolved.instrument_id, "status": "RESOLVED"}))
        return 0
    if args.dry_run:
        cutoff = datetime(2026, 1, 6, tzinfo=timezone.utc)
        exchange_sessions: frozenset[date] | None = frozenset({date(2026, 1, 5)})
    else:
        cutoff = completed_daily_cutoff(datetime.now(timezone.utc))
        # A real five-year PASS needs a separately verified exchange calendar.
        # A missing calendar must not be replaced by one synthetic session.
        exchange_sessions = None
    reports = []
    for ticker in ("AAPL", "MSFT", "SPY", "QQQ"):
        resolved = client.resolve_instrument(ticker)
        candles = client.fetch_daily_candles(resolved, cutoff=cutoff)
        reports.append(client.scan_five_year_daily(resolved, cutoff=cutoff, candles=candles, exchange_sessions=exchange_sessions).__dict__)
    print(json.dumps({"mode": "dry-run" if args.dry_run else "live-read-only", "reports": reports}, default=str, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
