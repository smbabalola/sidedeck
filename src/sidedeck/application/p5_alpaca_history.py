"""Research-only Alpaca IEX daily stock bars; never an Alpaca trading endpoint.

The fetcher intentionally leaves corporate-action verification false. Exchange-
specific IEX bars and split-adjusted output require independent reconciliation.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

_ENDPOINT = "https://data.alpaca.markets/v2/stocks"
_MAX_PAGES = 20
_ALLOWED_FEEDS = frozenset(("iex", "sip"))
_ALLOWED_ADJUSTMENTS = frozenset(("raw", "split", "dividend", "spin-off", "all"))


class MarketDataUnavailable(ValueError):
    pass


class PersistentRequestBudget:
    """Crash-safe request ceiling shared by retries, pages and restarts."""

    def __init__(self, path: str | Path, *, scope: str, maximum: int = 20):
        if not isinstance(maximum, int) or isinstance(maximum, bool) or maximum <= 0:
            raise MarketDataUnavailable("invalid persistent request budget")
        self.path = Path(path)
        self.scope = scope
        self.maximum = maximum
        self._state = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"schema_version": 1, "scope": self.scope, "maximum": self.maximum,
                    "requests_used": 0, "completed": False}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise MarketDataUnavailable("request budget cannot be read") from exc
        if (not isinstance(data, dict) or data.get("schema_version") != 1
                or data.get("scope") != self.scope or data.get("maximum") != self.maximum
                or type(data.get("requests_used")) is not int
                or not 0 <= data["requests_used"] <= self.maximum
                or type(data.get("completed")) is not bool):
            raise MarketDataUnavailable("request budget scope or state is invalid")
        return data

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".sidedeck-budget-", dir=str(self.path.parent))
        try:
            if os.name != "nt":
                os.chmod(temporary, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(self._state, stream, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def reserve(self) -> None:
        if self._state["completed"] or self._state["requests_used"] >= self.maximum:
            raise MarketDataUnavailable("historical request budget exhausted")
        self._state["requests_used"] += 1
        self._save()

    def complete(self) -> None:
        self._state["completed"] = True
        self._save()

    @property
    def requests_used(self) -> int:
        return int(self._state["requests_used"])


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
    budget: PersistentRequestBudget | None = None, cutoff: date | None = None,
) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Z][A-Z0-9.]{0,9}", ticker):
        raise MarketDataUnavailable("unsupported ticker")
    try:
        first, last = date.fromisoformat(start[:10]), date.fromisoformat(end[:10])
    except ValueError as exc:
        raise MarketDataUnavailable("invalid date range") from exc
    cutoff = cutoff or last
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
    status_codes: list[int] = []
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
            if budget is not None:
                budget.reserve()
            try:
                with opener(req, timeout=20) as response:
                    status = getattr(response, "status", None)
                    if isinstance(status, int):
                        status_codes.append(status)
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
        records.extend(parse_bars(payload, cutoff=cutoff, ticker=ticker))
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
    records = [record for record in records if record["date"] <= cutoff.isoformat()]
    if not records:
        raise MarketDataUnavailable("no historical bars in authorized date window")
    records.sort(key=lambda row: row["date"])
    if budget is not None:
        budget.complete()
    dates = [date.fromisoformat(record["date"]) for record in records]
    weekday_gaps = [day.isoformat() for left, right in zip(dates, dates[1:])
                     for offset in range(1, (right - left).days)
                     for day in (left + timedelta(days=offset),) if day.weekday() < 5]
    return {
        "ticker": ticker, "instrument_id": "US:" + ticker, "exchange": "NASDAQ",
        "currency": "USD", "session": "REGULAR",
        "price_basis": "split_adjusted_close" if adjustment == "split" else adjustment + "_close",
        "corporate_actions_verified": False,
        "source": url, "source_identity": "alpaca_market_data_api",
        "feed": feed, "adjustment": adjustment,
        "historical_price_validation": "PENDING",
        "research_only": True, "records": records,
        "request_count": budget.requests_used if budget is not None else len(status_codes),
        "http_statuses": status_codes, "pagination_pages": len(seen_tokens) + 1,
        "first_trading_date": records[0]["date"], "last_trading_date": records[-1]["date"],
        "weekday_gaps": weekday_gaps, "retrieved_at": datetime.now(timezone.utc).isoformat(),
    }


def fetch_alpaca_iex(
    ticker: str, start: str, end: str, *, key_id: str, secret: str,
    open_url: Any = None, budget: PersistentRequestBudget | None = None,
) -> dict[str, Any]:
    return fetch_alpaca_history(ticker, start, end, key_id=key_id, secret=secret,
                                feed="iex", adjustment="split", open_url=open_url, budget=budget)


def fetch_alpaca_sip(
    ticker: str, start: str, end: str, *, key_id: str, secret: str,
    open_url: Any = None, budget: PersistentRequestBudget | None = None,
    cutoff: date | None = None,
) -> dict[str, Any]:
    return fetch_alpaca_history(ticker, start, end, key_id=key_id, secret=secret,
                                feed="sip", adjustment="split", open_url=open_url,
                                budget=budget, cutoff=cutoff)


def main() -> int:
    parser = argparse.ArgumentParser(description="Alpaca historical IEX daily prices only")
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--feed", choices=sorted(_ALLOWED_FEEDS), default="iex")
    parser.add_argument("--budget-file", required=True)
    parser.add_argument("--cutoff-date", default="")
    parser.add_argument("--env-file", default="")
    parser.add_argument("--key-id-env", default="APCA_API_KEY_ID")
    parser.add_argument("--secret-env", default="APCA_API_SECRET_KEY")
    args = parser.parse_args()
    target = Path(args.output)
    if target.exists():
        parser.error("refusing to overwrite output")
    key = _credential(args.env_file, args.key_id_env)
    secret = _credential(args.env_file, args.secret_env)
    scope = "|".join((args.ticker, args.start, args.end, args.feed, "split"))
    budget = PersistentRequestBudget(args.budget_file, scope=scope, maximum=20)
    cutoff = date.fromisoformat(args.cutoff_date) if args.cutoff_date else None
    result = fetch_alpaca_history(args.ticker, args.start, args.end, key_id=key, secret=secret,
                                  feed=args.feed, adjustment="split", budget=budget, cutoff=cutoff)
    target.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"HISTORICAL_{args.feed.upper()}_BARS={len(result['records'])}")
    print(f"REQUESTS_USED={budget.requests_used}; REQUEST_BUDGET=20")
    print("CORPORATE_ACTION_VERIFICATION=PENDING")
    print("BUFFETT_SNAPSHOT=NOT_READY; BROKER_EXECUTION=DISABLED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
