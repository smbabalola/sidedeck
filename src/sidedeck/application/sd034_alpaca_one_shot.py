"""One-time, bounded SD-034 Alpaca PAPER read-only verification.

This is intentionally not a reusable broker client. It permits exactly three
GET attempts, one per approved path, then becomes permanently exhausted.
Responses are inspected in memory and reduced to coarse sanitized evidence.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.parse import urlparse

HOST = "paper-api.alpaca.markets"
BASE_URL = f"https://{HOST}"
APPROVED_PATHS = ("/v2/account", "/v2/positions", "/v2/orders")
MAX_ATTEMPTS = 3


class OneShotError(RuntimeError):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req: Request, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


def _load_local_env(path: str = ".env") -> None:
    """Load only the two explicitly approved names; never print values."""
    target = Path(path)
    if not target.is_file() or target.is_symlink():
        return
    for raw in target.read_text(encoding="utf-8").splitlines():
        if "=" not in raw or raw.lstrip().startswith("#"):
            continue
        name, value = raw.split("=", 1)
        if name.strip() in {"ALPACA_API_KEY", "ALPACA_API_SECRET"}:
            os.environ.setdefault(name.strip(), value.strip().strip('"\''))


def _reserve(db_path: str, endpoint: str) -> None:
    if endpoint not in APPROVED_PATHS:
        raise OneShotError("endpoint is outside the one-shot allowlist")
    db = sqlite3.connect(db_path, isolation_level=None)
    try:
        db.execute("CREATE TABLE IF NOT EXISTS sd034_budget (endpoint TEXT PRIMARY KEY, attempts INTEGER NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS sd034_total (singleton INTEGER PRIMARY KEY, attempts INTEGER NOT NULL)")
        db.execute("INSERT OR IGNORE INTO sd034_total VALUES (1, 0)")
        db.execute("BEGIN IMMEDIATE")
        total = int(db.execute("SELECT attempts FROM sd034_total WHERE singleton=1").fetchone()[0])
        prior = db.execute("SELECT attempts FROM sd034_budget WHERE endpoint=?", (endpoint,)).fetchone()
        if total >= MAX_ATTEMPTS or (prior is not None and prior[0] >= 1):
            raise OneShotError("SD-034 request budget exhausted")
        db.execute("INSERT INTO sd034_budget(endpoint, attempts) VALUES (?, 1) ON CONFLICT(endpoint) DO UPDATE SET attempts=attempts+1", (endpoint,))
        db.execute("UPDATE sd034_total SET attempts=attempts+1 WHERE singleton=1")
        db.execute("COMMIT")
    except Exception:
        if db.in_transaction:
            db.execute("ROLLBACK")
        raise
    finally:
        db.close()


def _schema_summary(endpoint: str, status: int, payload: object) -> dict[str, Any]:
    result: dict[str, Any] = {"endpoint": endpoint, "http_status": status, "schema_status": "INVALID", "account_separation": "UNVERIFIED"}
    if status != 200:
        result["failure"] = "HTTP_REJECTED"
        return result
    if endpoint == "/v2/account":
        if not isinstance(payload, dict) or not isinstance(payload.get("status"), str) or payload.get("currency") != "USD":
            result["failure"] = "ACCOUNT_SCHEMA_INVALID"
            return result
        result.update({"schema_status": "VALID", "paper_environment": "UNVERIFIED", "account_status": payload["status"],
                       "identity": "PRESENT_BUT_WITHHELD", "account_separation": "UNVERIFIED"})
        return result
    if not isinstance(payload, list):
        result["failure"] = "LIST_SCHEMA_INVALID"
        return result
    if endpoint == "/v2/positions":
        result.update({"schema_status": "VALID", "positions_present": bool(payload),
                       "position_count": len(payload), "ownership": "UNRESOLVED" if payload else "NOT_APPLICABLE"})
    else:
        open_orders = [item for item in payload if isinstance(item, dict) and item.get("status") in {"open", "new", "partially_filled", "accepted", "pending_new"}]
        result.update({"schema_status": "VALID", "orders_present": bool(payload), "order_count": len(payload),
                       "open_or_unresolved": bool(open_orders), "ownership": "UNRESOLVED" if payload else "NOT_APPLICABLE"})
    return result


def request_once(endpoint: str, *, budget_path: str, timeout_seconds: float = 10.0) -> dict[str, Any]:
    parsed = urlparse(BASE_URL)
    if parsed.scheme != "https" or parsed.hostname != HOST or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise OneShotError("approved PAPER host validation failed")
    _reserve(budget_path, endpoint)
    key = os.environ.get("ALPACA_API_KEY")
    secret = os.environ.get("ALPACA_API_SECRET")
    if not key or not secret:
        return {"endpoint": endpoint, "http_status": None, "schema_status": "NOT_REQUESTED", "failure": "CREDENTIALS_UNAVAILABLE",
                "account_separation": "UNVERIFIED"}
    request = Request(BASE_URL + endpoint, method="GET", headers={
        "APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret, "Accept": "application/json"})
    try:
        with build_opener(_NoRedirect()).open(request, timeout=timeout_seconds) as response:
            body = response.read(2_000_001)
            if len(body) > 2_000_000:
                return {"endpoint": endpoint, "http_status": response.status, "schema_status": "INVALID",
                        "failure": "RESPONSE_TOO_LARGE", "account_separation": "UNVERIFIED"}
            return _schema_summary(endpoint, response.status, json.loads(body))
    except HTTPError as exc:
        return {"endpoint": endpoint, "http_status": exc.code, "schema_status": "NOT_VERIFIED",
                "failure": "HTTP_REJECTED", "account_separation": "UNVERIFIED"}
    except (URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
        return {"endpoint": endpoint, "http_status": None, "schema_status": "NOT_VERIFIED",
                "failure": "REQUEST_FAILED", "account_separation": "UNVERIFIED"}


def main() -> int:
    parser = argparse.ArgumentParser(description="One-time SD-034 Alpaca PAPER read-only verification")
    parser.add_argument("--budget", required=True)
    args = parser.parse_args()
    _load_local_env()
    report: dict[str, Any] = {"schema_version": 1, "authorization": "SD-034-ONE-SHOT", "attempt_limit": 3,
                               "paper_release": "NO_GO", "broker_execution": "DISABLED", "live_trading": "PROHIBITED", "endpoints": []}
    for endpoint in APPROVED_PATHS:
        report["endpoints"].append(request_once(endpoint, budget_path=args.budget))
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
