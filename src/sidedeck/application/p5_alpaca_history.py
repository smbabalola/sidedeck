"""Research-only Alpaca IEX daily stock bars; never an Alpaca trading endpoint.

The fetcher intentionally leaves corporate-action verification false. Exchange-
specific IEX bars and split-adjusted output require independent reconciliation.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any

_ENDPOINT = "https://data.alpaca.markets/v2/stocks"
_MAX_PAGES = 20


class MarketDataUnavailable(ValueError):
    pass


def _credential(path: str, name: str) -> str:
    existing = os.environ.get(name)
    if existing:
        return existing
    if not path:
        raise MarketDataUnavailable("market-data credential not present in environment")
    for raw in Path(path).read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if line.startswith("export "):
            line = line[7:].strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == name:
            value = value.strip().strip('"').strip("'")
            if value:
                return value
    raise MarketDataUnavailable("market-data credential not present in env-file")


def parse_bars(payload: dict[str, Any], *, cutoff: date) -> list[dict[str, Any]]:
    bars = payload.get("bars")
    if not isinstance(bars, list):
        raise MarketDataUnavailable("invalid market-data bars")
    results: list[dict[str, Any]] = []
    for row in bars:
        if not isinstance(row, dict):
            raise MarketDataUnavailable("invalid market-data bar")
        stamp = row.get("t")
        close = row.get("c")
        if not isinstance(stamp, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T.*", stamp):
            raise MarketDataUnavailable("bar timestamp missing")
        try:
            day = date.fromisoformat(stamp[:10])
        except ValueError as exc:
            raise MarketDataUnavailable("invalid bar timestamp") from exc
        if day > cutoff or isinstance(close, bool) or not isinstance(close, (float, int)):
            raise MarketDataUnavailable("future bar or invalid close")
        if not math.isfinite(close) or close <= 0:
            raise MarketDataUnavailable("invalid close")
        results.append({"date": day.isoformat(), "close": close,
                        "source_id": "alpaca:iex:1Day:split:" + stamp})
    return results


def fetch_alpaca_iex(
    ticker: str, start: str, end: str, *, key_id: str, secret: str,
    open_url: Any = None,
) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Z][A-Z0-9.]{0,9}", ticker):
        raise MarketDataUnavailable("unsupported ticker")
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if first > last:
        raise MarketDataUnavailable("invalid date range")
    if not key_id or not secret:
        raise MarketDataUnavailable("missing market-data credentials")
    url = _ENDPOINT + "/" + ticker + "/bars"
    token: str | None = None
    records: list[dict[str, Any]] = []
    seen_tokens: set[str] = set()
    opener = open_url or urllib.request.urlopen
    for _ in range(_MAX_PAGES):
        params = {"timeframe": "1Day", "start": start, "end": end,
                  "feed": "iex", "adjustment": "split", "limit": "10000"}
        if token is not None:
            params["page_token"] = token
        req = urllib.request.Request(url + "?" + urllib.parse.urlencode(params), headers={
            "APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": secret,
            "Accept": "application/json",
        })
        try:
            with opener(req, timeout=20) as response:
                raw = response.read(8_000_001)
                if len(raw) > 8_000_000:
                    raise MarketDataUnavailable("response too large")
                payload = json.loads(raw)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise MarketDataUnavailable("Alpaca market-data request failed") from exc
        if not isinstance(payload, dict):
            raise MarketDataUnavailable("invalid response")
        records.extend(parse_bars(payload, cutoff=last))
        next_token = payload.get("next_page_token")
        if next_token is None:
            break
        if not isinstance(next_token, str) or not next_token or next_token in seen_tokens:
            raise MarketDataUnavailable("invalid pagination cursor")
        seen_tokens.add(next_token)
        token = next_token
    else:
        raise MarketDataUnavailable("price history exceeded page budget")
    dates = [record["date"] for record in records]
    if len(dates) != len(set(dates)):
        raise MarketDataUnavailable("duplicate trading dates")
    if not records:
        raise MarketDataUnavailable("no historical IEX bars for requested range")
    records.sort(key=lambda row: row["date"])
    return {
        "ticker": ticker, "currency": "USD",
        "price_basis": "split_adjusted_close",
        "corporate_actions_verified": False,
        "source": url,
        "feed": "iex", "adjustment": "split",
        "historical_price_validation": "PENDING",
        "research_only": True, "records": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Alpaca historical IEX daily prices only")
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--env-file", default="")
    parser.add_argument("--key-id-env", default="APCA_API_KEY_ID")
    parser.add_argument("--secret-env", default="APCA_API_SECRET_KEY")
    args = parser.parse_args()
    target = Path(args.output)
    if target.exists():
        parser.error("refusing to overwrite output")
    key = _credential(args.env_file, args.key_id_env)
    secret = _credential(args.env_file, args.secret_env)
    result = fetch_alpaca_iex(args.ticker, args.start, args.end, key_id=key, secret=secret)
    target.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"HISTORICAL_IEX_BARS={len(result['records'])}")
    print("CORPORATE_ACTION_VERIFICATION=PENDING")
    print("BUFFETT_SNAPSHOT=NOT_READY; BROKER_EXECUTION=DISABLED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
