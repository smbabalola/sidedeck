"""Explicitly opt-in, market-data-only eToro probe.

This command is intentionally inert unless both owner-confirmation flags are
provided. It is not used by tests and has no order, portfolio or broker-write
capability.
"""

from __future__ import annotations

import argparse
import os
from typing import Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import UUID

from sidedeck.domain.etoro import (
    ETORO_BASE_URL,
    EtoroHistoricalDataClient,
    MarketDataReadCapability,
    ReadOnlyMarketDataTransport,
)


class UrllibReadOnlyTransport(ReadOnlyMarketDataTransport):
    def __init__(self, headers: Mapping[str, str]) -> None:
        self._headers = dict(headers)

    def get(self, path: str, params: Mapping[str, str], request_id: UUID) -> tuple[int, Mapping[str, str], bytes]:
        url = f"{ETORO_BASE_URL}{path}"
        if params:
            url = f"{url}?{urlencode(params)}"
        request = Request(url, headers={**self._headers, "x-request-id": str(request_id), "Accept": "application/json"}, method="GET")
        with urlopen(request, timeout=10) as response:  # noqa: S310 - fixed official host and GET only
            return response.status, dict(response.headers.items()), response.read()


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only eToro historical market-data probe")
    parser.add_argument("--provider", choices=("etoro",), required=True)
    parser.add_argument("--market-data-only", action="store_true")
    parser.add_argument("--allow-read-network", action="store_true")
    parser.add_argument("--confirm-owner-read-only", action="store_true")
    args = parser.parse_args()
    if not args.market_data_only or not args.allow_read_network or not args.confirm_owner_read_only:
        parser.error("requires --market-data-only --allow-read-network --confirm-owner-read-only")
    api_key = os.environ.get("ETORO_API_KEY")
    user_key = os.environ.get("ETORO_USER_KEY")
    if not api_key or not user_key:
        parser.error("ETORO_API_KEY and ETORO_USER_KEY are required only after owner approval")
    client = EtoroHistoricalDataClient(
        UrllibReadOnlyTransport({"x-api-key": api_key, "x-user-key": user_key}),
        capability=MarketDataReadCapability(),
    )
    # The probe currently resolves only; callers must explicitly request and
    # validate candles through the typed client. No default Yahoo fallback.
    print(client.resolve_instrument("AAPL"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
