"""Research-only Alpaca IEX daily stock bars; never an Alpaca trading endpoint.

The fetcher intentionally leaves corporate-action verification false. Exchange-
specific IEX bars and split-adjusted output require independent reconciliation.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

_ENDPOINT = "https://data.alpaca.markets/v2/stocks"
_MAX_PAGES = 20
_ALLOWED_FEEDS = frozenset(("iex", "sip"))
_ALLOWED_ADJUSTMENTS = frozenset(("raw", "split", "dividend", "spin-off", "all"))


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


def _positive_decimal(value: Any, field: str) -> Decimal:
    if isinstance(value, bool):
        raise MarketDataUnavailable(f"invalid {field}")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise MarketDataUnavailable(f"invalid {field}") from exc
    if not result.is_finite() or result <= 0:
        raise MarketDataUnavailable(f"invalid {field}")
    return result


def parse_bars(payload: dict[str, Any], *, cutoff: date, ticker: str = "") -> list[dict[str, Any]]:
    bars = payload.get("bars")
    if not isinstance(bars, list):
        raise MarketDataUnavailable("invalid market-data bars")
    results: list[dict[str, Any]] = []
    for row in bars:
        if not isinstance(row, dict):
            raise MarketDataUnavailable("invalid market-data bar")
        stamp = row.get("t")
        if not isinstance(stamp, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T.*", stamp):
            raise MarketDataUnavailable("bar timestamp missing")
        try:
            day = date.fromisoformat(stamp[:10])
        except ValueError as exc:
            raise MarketDataUnavailable("invalid bar timestamp") from exc
        if day > cutoff:
            raise MarketDataUnavailable("future bar or invalid close")
        values = {field: _positive_decimal(row.get(key), field)
                  for field, key in (("open", "o"), ("high", "h"), ("low", "l"),
                                     ("close", "c"), ("volume", "v"))}
        if values["high"] < max(values["open"], values["close"]) or values["low"] > min(values["open"], values["close"]):
            raise MarketDataUnavailable("inconsistent OHLC range")
        results.append({"date": day.isoformat(), "timestamp": stamp, **{k: str(v) for k, v in values.items()},
                        "ticker": ticker, "source_id": "alpaca:1Day:" + stamp})
    return results


def fetch_alpaca_history(
    ticker: str, start: str, end: str, *, key_id: str, secret: str,
    feed: str = "iex", adjustment: str = "split", open_url: Any = None,
    max_retries: int = 1, sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Z][A-Z0-9.]{0,9}", ticker):
        raise MarketDataUnavailable("unsupported ticker")
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if first > last:
        raise MarketDataUnavailable("invalid date range")
    if feed not in _ALLOWED_FEEDS or adjustment not in _ALLOWED_ADJUSTMENTS:
        raise MarketDataUnavailable("unsupported feed or adjustment")
    if not isinstance(max_retries, int) or isinstance(max_retries, bool) or not 0 <= max_retries <= 2:
        raise MarketDataUnavailable("invalid retry budget")
    if not key_id or not secret:
        raise MarketDataUnavailable("missing market-data credentials")
    url = _ENDPOINT + "/" + ticker + "/bars"
    token: str | None = None
    records: list[dict[str, Any]] = []
    seen_tokens: set[str] = set()
    opener = open_url or urllib.request.urlopen
    for _ in range(_MAX_PAGES):
        params = {"timeframe": "1Day", "start": start, "end": end,
                  "feed": feed, "adjustment": adjustment, "currency": "USD", "sort": "asc", "limit": "10000"}
        if token is not None:
            params["page_token"] = token
        req = urllib.request.Request(url + "?" + urllib.parse.urlencode(params), headers={
            "APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": secret,
            "Accept": "application/json",
        })
        for attempt in range(max_retries + 1):
            try:
                with opener(req, timeout=20) as response:
                    raw = response.read(8_000_001)
                    if len(raw) > 8_000_000:
                        raise MarketDataUnavailable("response too large")
                    payload = json.loads(raw)
                break
            except urllib.error.HTTPError as exc:
                if exc.code not in (429, 500, 502, 503) or attempt == max_retries:
                    raise MarketDataUnavailable("Alpaca market-data request failed") from None
                sleep(min(2 ** attempt, 2))
            except (urllib.error.URLError, OSError, ValueError) as exc:
                if attempt == max_retries:
                    raise MarketDataUnavailable("Alpaca market-data request failed") from exc
                sleep(min(2 ** attempt, 2))
        else:
            raise MarketDataUnavailable("Alpaca market-data request failed")
        if not isinstance(payload, dict):
            raise MarketDataUnavailable("invalid response")
        records.extend(parse_bars(payload, cutoff=last, ticker=ticker))
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
        "ticker": ticker, "instrument_id": "US:" + ticker, "exchange": "NASDAQ",
        "currency": "USD", "session": "REGULAR",
        "price_basis": "split_adjusted_close" if adjustment == "split" else adjustment + "_close",
        "corporate_actions_verified": False,
        "source": url, "source_identity": "alpaca_market_data_api",
        "feed": feed, "adjustment": adjustment,
        "historical_price_validation": "PENDING",
        "research_only": True, "records": records,
    }


def fetch_alpaca_iex(
    ticker: str, start: str, end: str, *, key_id: str, secret: str,
    open_url: Any = None,
) -> dict[str, Any]:
    return fetch_alpaca_history(ticker, start, end, key_id=key_id, secret=secret,
                                feed="iex", adjustment="split", open_url=open_url)


def fetch_alpaca_sip(
    ticker: str, start: str, end: str, *, key_id: str, secret: str,
    open_url: Any = None,
) -> dict[str, Any]:
    return fetch_alpaca_history(ticker, start, end, key_id=key_id, secret=secret,
                                feed="sip", adjustment="split", open_url=open_url)


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
