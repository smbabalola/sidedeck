"""Single-use, two-request Alpaca PAPER account identity comparison."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

HOST = "paper-api.alpaca.markets"
BASE_URL = f"https://{HOST}"
ENDPOINT = "/v2/account"
PAIRS = {
    "A": ("ALPACA_API_KEY", "ALPACA_API_SECRET"),
    "B": ("ALPACA_API_KEY2", "ALPACA_API_SECRET2"),
}


class SeparationError(RuntimeError):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req: Request, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


def load_local_env(path: str = ".env") -> None:
    target = Path(path)
    if not target.is_file() or target.is_symlink():
        return
    for raw in target.read_text(encoding="utf-8").splitlines():
        if "=" not in raw or raw.lstrip().startswith("#"):
            continue
        name, value = raw.split("=", 1)
        if name.strip() in {item for pair in PAIRS.values() for item in pair}:
            os.environ.setdefault(name.strip(), value.strip().strip('"\''))


def reserve_attempt(db_path: str, pair: str) -> None:
    if pair not in PAIRS:
        raise SeparationError("credential pair is not authorized")
    db = sqlite3.connect(db_path, isolation_level=None)
    try:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS sd035_budget(pair TEXT PRIMARY KEY, attempts INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS sd035_total(singleton INTEGER PRIMARY KEY, attempts INTEGER NOT NULL);
            INSERT OR IGNORE INTO sd035_total VALUES (1, 0);
            """
        )
        db.execute("BEGIN IMMEDIATE")
        total = int(db.execute("SELECT attempts FROM sd035_total WHERE singleton=1").fetchone()[0])
        prior = db.execute("SELECT attempts FROM sd035_budget WHERE pair=?", (pair,)).fetchone()
        if total >= 2 or (prior is not None and prior[0] >= 1):
            raise SeparationError("SD-035 request budget exhausted")
        db.execute("INSERT INTO sd035_budget VALUES (?, 1) ON CONFLICT(pair) DO UPDATE SET attempts=attempts+1", (pair,))
        db.execute("UPDATE sd035_total SET attempts=attempts+1 WHERE singleton=1")
        db.execute("COMMIT")
    except Exception:
        if db.in_transaction:
            db.execute("ROLLBACK")
        raise
    finally:
        db.close()


def validate_account(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    identity = payload.get("id")
    if not isinstance(identity, str) or not identity.strip():
        return None
    return identity


def compare_identities(pair_a: str | None, pair_b: str | None) -> str:
    if pair_a is None or pair_b is None:
        return "UNVERIFIED"
    return "SAME" if pair_a == pair_b else "DISTINCT"


def request_once(pair: str, *, budget_path: str, timeout_seconds: float = 10.0) -> dict[str, Any]:
    parsed = urlparse(BASE_URL)
    if parsed.scheme != "https" or parsed.hostname != HOST or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise SeparationError("approved PAPER host validation failed")
    reserve_attempt(budget_path, pair)
    key_name, secret_name = PAIRS[pair]
    key = os.environ.get(key_name)
    secret = os.environ.get(secret_name)
    result: dict[str, Any] = {"pair": pair, "attempted": True, "http_status": None, "schema_status": "NOT_VERIFIED"}
    if not key or not secret:
        result["failure"] = "CREDENTIALS_UNAVAILABLE"
        return result
    request = Request(BASE_URL + ENDPOINT, method="GET", headers={
        "APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret, "Accept": "application/json"})
    try:
        with build_opener(_NoRedirect()).open(request, timeout=timeout_seconds) as response:
            result["http_status"] = response.status
            if response.status != 200:
                result["failure"] = "HTTP_REJECTED"
                return result
            body = response.read(2_000_001)
            if len(body) > 2_000_000:
                result["failure"] = "RESPONSE_TOO_LARGE"
                return result
            identity = validate_account(json.loads(body))
            result["schema_status"] = "VALID" if identity is not None else "INVALID"
            result["_identity"] = identity
            return result
    except HTTPError as exc:
        result["http_status"] = exc.code
        result["failure"] = "HTTP_REJECTED"
        return result
    except (URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
        result["failure"] = "REQUEST_FAILED"
        return result


def run_comparison(budget_path: str) -> dict[str, Any]:
    load_local_env()
    first = request_once("A", budget_path=budget_path)
    second = request_once("B", budget_path=budget_path)
    status = compare_identities(first.pop("_identity", None), second.pop("_identity", None))
    return {"schema_version": 1, "authorization": "SD-035-ONE-SHOT", "comparison": status,
            "paper_release": "NO_GO", "broker_execution": "DISABLED", "live_trading": "PROHIBITED",
            "attempt_limit": 2, "attempts_consumed": 2, "pairs": [first, second]}


def main() -> int:
    parser = argparse.ArgumentParser(description="Single-use SD-035 account-separation verification")
    parser.add_argument("--budget", required=True)
    args = parser.parse_args()
    print(json.dumps(run_comparison(args.budget), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
