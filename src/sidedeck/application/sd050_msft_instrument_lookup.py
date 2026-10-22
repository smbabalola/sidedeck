"""SD-050 one-shot, owner-authorized eToro MSFT instrument lookup (read-only).

Exactly one ``GET /api/v1/market-data/search?internalSymbolFull=MSFT&fields=...``
(``fields`` is required by the documented API) under a persistent single-attempt
budget reserved before sending. No retry, redirect, pagination or other endpoint.

Acceptance is exact: exactly one item whose ``internalSymbolFull`` is ``MSFT`` with a
positive integer ``instrumentId``; otherwise it fails closed and nothing is retained (the
ID is never guessed). That unique candidate must then be on Nasdaq, not delisted, not
hidden and not a non-stock type. A candidate failing one of these is *retained* as
``CANDIDATE_REJECTED`` evidence (ID plus labels) so an authorized request is never
wasted, but it is not usable by the pilot. Flags eToro omits (listing status, type) are
listed in ``unverified_fields``; the pilot preflight (Demo eligibility + realtime rates)
independently verifies tradability before any order. The baseline database is opened
read-only and only a yes/no "conflicts with a protected instrument" answer is reported.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from sidedeck.application.sd042_etoro_credential_roles import (
    DEMO_PAIR_NAMES, LEGACY_NAMES, monitoring_credentials,
)

AUTHORIZATION_ID = "SD-050"
# Each lookup needs an owner authorization recorded HERE in reviewed code. SD-050 was
# consumed (2026-10-22) and is refused unconditionally, even if its budget file is lost.
# SD-052: owner authorization (2026-10-22) for exactly one more MSFT search GET.
AUTHORIZED_LOOKUP_IDS: frozenset[str] = frozenset({"SD-052"})
EXHAUSTED_LOOKUP_IDS = frozenset({"SD-050"})
LOOKUP_NETWORK_ENABLED = False   # network lock; a reviewed commit enables one authorized id
_AUTH_ID = re.compile(r"SD-[0-9]{3}")
DATA_DIR = Path(__file__).resolve().parents[3] / "data"
SYMBOL = "MSFT"
SEARCH_URL = "https://public-api.etoro.com/api/v1/market-data/search"
FIELDS = ("instrumentId,internalSymbolFull,internalExchangeName,instrumentType,instrumentTypeID,"
          "displayname,isDelisted,isHiddenFromClient,isCurrentlyTradable,isBuyEnabled,currentRate")
TIMEOUT_SECONDS = 15.0
MAX_RESPONSE_BYTES = 1_000_000


class LookupRefused(RuntimeError):
    """A precondition failed; no request was sent."""


class CandidateRejected(LookupRefused):
    """A unique exact-symbol candidate failed validation; kept as evidence only."""

    def __init__(self, reason: str, item: dict[str, Any]) -> None:
        super().__init__(reason)
        self.item = item


class Opener(Protocol):
    def open(self, request: Request, timeout: float) -> Any: ...


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args: Any) -> None:
        raise LookupRefused("redirect refused")


def load_local_credentials(path: str = ".env") -> dict[str, str]:
    """Only the policy-relevant names, returned (not exported); never printed."""
    env: dict[str, str] = {}
    target = Path(path)
    if not target.is_file() or target.is_symlink():
        return env
    for raw in target.read_text(encoding="utf-8").splitlines():
        if "=" not in raw or raw.lstrip().startswith("#"):
            continue
        name, value = raw.split("=", 1)
        if name.strip() in DEMO_PAIR_NAMES + LEGACY_NAMES:
            env[name.strip()] = value.strip().strip('"\'')
    return env


def budget_path_for(authorization_id: str) -> str:
    """Validated id -> absolute budget path under the repository data/ directory."""
    if not _AUTH_ID.fullmatch(authorization_id):
        raise LookupRefused("authorization id must look like SD-123")
    name = authorization_id.lower().replace("-", "") + "-auth-budget.sqlite3"
    return str(DATA_DIR / name)


def _budget(path: str) -> sqlite3.Connection:
    db = sqlite3.connect(path, isolation_level=None)
    db.execute("CREATE TABLE IF NOT EXISTS sd050_budget (singleton INTEGER PRIMARY KEY CHECK "
               "(singleton = 1), attempts INTEGER NOT NULL, outcome TEXT NOT NULL, "
               "updated_at TEXT NOT NULL)")
    return db


def attempts_consumed(path: str) -> int:
    if not Path(path).is_file():
        return 0
    db = _budget(path)
    try:
        row = db.execute("SELECT attempts FROM sd050_budget").fetchone()
        return 0 if row is None else int(row[0])
    finally:
        db.close()


def record_authorization(authorization_id: str, scope: str, *, path: str | None = None) -> str:
    """Create the durable single-use ledger for a new owner authorization (no attempt
    consumed). Refuses consumed ids and never resets an existing ledger."""
    target = path or budget_path_for(authorization_id)
    if authorization_id in EXHAUSTED_LOOKUP_IDS or attempts_consumed(target):
        raise LookupRefused(f"{authorization_id} is exhausted; ledger not reset")
    db = _budget(target)
    try:
        db.execute("CREATE TABLE IF NOT EXISTS lookup_authorization (authorization_id TEXT "
                   "PRIMARY KEY, scope TEXT NOT NULL, recorded_at TEXT NOT NULL)")
        db.execute("INSERT OR IGNORE INTO lookup_authorization VALUES (?, ?, ?)",
                   (authorization_id, scope, datetime.now(timezone.utc).isoformat()))
    finally:
        db.close()
    return target


def _reserve(path: str) -> None:
    db = _budget(path)
    try:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT attempts FROM sd050_budget").fetchone() is not None:
            raise LookupRefused("lookup authorization is exhausted; no request sent")
        db.execute("INSERT INTO sd050_budget VALUES (1, 1, 'RESERVED', ?)",
                   (datetime.now(timezone.utc).isoformat(),))
        db.execute("COMMIT")
    except BaseException:
        if db.in_transaction:
            db.execute("ROLLBACK")
        raise
    finally:
        db.close()


def _outcome(path: str, outcome: str) -> None:
    db = _budget(path)
    try:
        db.execute("UPDATE sd050_budget SET outcome=?, updated_at=?",
                   (outcome, datetime.now(timezone.utc).isoformat()))
    finally:
        db.close()


def baseline_instrument_ids(db_path: str) -> frozenset[int]:
    target = Path(db_path)
    if not target.is_file() or target.is_symlink():
        raise LookupRefused("baseline database missing")
    db = sqlite3.connect(target.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        rows = db.execute("SELECT instrument_id FROM etoro_demo_baseline").fetchall()
    finally:
        db.close()
    if len(rows) != 4:
        raise LookupRefused("baseline does not hold exactly four protected positions")
    return frozenset(int(r[0]) for r in rows)


_STOCK_WORDS = ("stock", "equit", "share")


VERIFIED, UNVERIFIED, REJECTED = "VERIFIED", "UNVERIFIED", "REJECTED"


def _flag(value: Any, safe: bool) -> str:
    """Boolean attribute: the safe value verifies, the other rejects, absent is unknown."""
    if value is None:
        return UNVERIFIED
    return VERIFIED if value is safe else REJECTED


def attribute_verification(item: dict[str, Any]) -> dict[str, str]:
    """Per-attribute status. Absent optional fields are UNVERIFIED, never assumed safe."""
    exchange = item.get("internalExchangeName")
    name = item.get("displayname")
    kind = item.get("instrumentType")
    currencies = [v for k, v in item.items() if "currency" in k.lower() and v is not None]
    return {
        "symbol": VERIFIED,                     # exact match established by the caller
        "instrument_id": VERIFIED,
        "exchange": (VERIFIED if isinstance(exchange, str)
                     and exchange.strip().lower() == "nasdaq" else REJECTED),
        "issuer": (UNVERIFIED if name is None
                   else VERIFIED if isinstance(name, str) and "microsoft" in name.lower()
                   else REJECTED),
        "instrument_type": (UNVERIFIED if kind is None
                            else VERIFIED if any(w in str(kind).lower() for w in _STOCK_WORDS)
                            else REJECTED),
        "listing_status": _flag(item.get("isDelisted"), False),
        "visibility": _flag(item.get("isHiddenFromClient"), False),
        "currency": (UNVERIFIED if not currencies
                     else VERIFIED if all(str(c).strip().upper() == "USD" for c in currencies)
                     else REJECTED),
    }


def unverified_fields(item: dict[str, Any]) -> list[str]:
    return [k for k, v in attribute_verification(item).items() if v == UNVERIFIED]


def select_exact_match(payload: Any) -> dict[str, Any]:
    """Exactly one MSFT candidate with a valid ID; no attribute may be REJECTED."""
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        raise LookupRefused("search response lacks items")
    exact = [i for i in items if isinstance(i, dict) and i.get("internalSymbolFull") == SYMBOL]
    if len(exact) != 1:
        raise LookupRefused(f"expected exactly one exact {SYMBOL} match, found {len(exact)}")
    item = exact[0]
    instrument_id = item.get("instrumentId")
    if type(instrument_id) is not int or instrument_id <= 0:
        raise LookupRefused("instrumentId is invalid")
    rejected = [k for k, v in attribute_verification(item).items() if v == REJECTED]
    if rejected:
        raise CandidateRejected("exact match failed validation: " + ", ".join(rejected), item)
    return item


def match_diagnostics(payload: Any) -> dict[str, Any]:
    """Sanitized evidence for a non-accepted response: field names and JSON types only,
    plus the non-sensitive type/exchange labels of exact-symbol candidates."""
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return {"items": type(items).__name__}
    exact = [i for i in items if isinstance(i, dict) and i.get("internalSymbolFull") == SYMBOL]
    return {"item_count": len(items), "exact_symbol_matches": len(exact),
            "candidates": [{"fields": {k: type(v).__name__ for k, v in sorted(i.items())},
                            "instrumentType": i.get("instrumentType"),
                            "instrumentTypeID": i.get("instrumentTypeID"),
                            "internalExchangeName": i.get("internalExchangeName")}
                           for i in exact[:3]]}


def run_once(*, env: dict[str, str], db_path: str, budget_path: str, evidence_path: str,
             opener_factory: Callable[[], Opener] | None = None,
             authorization_id: str = AUTHORIZATION_ID,
             authorized_ids: frozenset[str] = AUTHORIZED_LOOKUP_IDS) -> dict[str, Any]:
    if (not _AUTH_ID.fullmatch(authorization_id) or authorization_id in EXHAUSTED_LOOKUP_IDS
            or authorization_id not in authorized_ids):
        raise LookupRefused("authorization id is not an open, owner-authorized lookup")
    if opener_factory is None and not LOOKUP_NETWORK_ENABLED:
        raise LookupRefused("lookup network access is locked")
    if attempts_consumed(budget_path):
        raise LookupRefused(f"{authorization_id} authorization is exhausted; no request sent")
    protected = baseline_instrument_ids(db_path)
    api_key, user_key = monitoring_credentials(env)          # single-pair policy (ADR-004)
    opener: Any = (opener_factory() if opener_factory
                   else build_opener(ProxyHandler({}), _NoRedirect()))  # pragma: no cover
    url = SEARCH_URL + "?" + urlencode({"internalSymbolFull": SYMBOL, "fields": FIELDS})
    request = Request(url, method="GET", headers={
        "x-api-key": api_key, "x-user-key": user_key, "x-request-id": str(uuid.uuid4()),
        "User-Agent": "SideDeck/0.1 (one-shot instrument lookup)", "Accept": "application/json"})
    _reserve(budget_path)
    base = {"authorization": authorization_id, "http_attempts_consumed": 1,
            "endpoint": "GET /api/v1/market-data/search", "orders_submitted": 0,
            "execution_release": "NO_GO"}
    try:
        response = opener.open(request, timeout=TIMEOUT_SECONDS)
        status, raw = int(response.status), response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        _outcome(budget_path, f"HTTP_{exc.code}")
        return {**base, "status": "FAILED_UNVERIFIED", "http_status": exc.code}
    except (URLError, OSError, LookupRefused):
        _outcome(budget_path, "NETWORK_ERROR")
        return {**base, "status": "FAILED_UNVERIFIED", "http_status": None}
    if status != 200 or len(raw) > MAX_RESPONSE_BYTES:
        _outcome(budget_path, f"UNEXPECTED_{status}")
        return {**base, "status": "FAILED_UNVERIFIED", "http_status": status}
    payload: Any = None
    rejection: str | None = None
    try:
        payload = json.loads(raw)
        item = select_exact_match(payload)
    except CandidateRejected as exc:
        item, rejection = exc.item, str(exc)
    except (ValueError, LookupRefused) as exc:
        _outcome(budget_path, "NO_EXACT_MATCH")
        diagnostics = match_diagnostics(payload)
        Path(evidence_path).with_suffix(".diagnostics.json").write_text(
            json.dumps(diagnostics, indent=2), encoding="utf-8")
        return {**base, "status": "FAILED_UNVERIFIED", "http_status": 200, "reason": str(exc),
                "diagnostics": diagnostics}
    conflict = item["instrumentId"] in protected
    verification = attribute_verification(item)
    result = ("CANDIDATE_REJECTED" if rejection
              else "BASELINE_CONFLICT_REJECTED" if conflict
              else "RESOLVED_PARTIALLY_VERIFIED" if UNVERIFIED in verification.values()
              else "RESOLVED")
    evidence = {"status": result, "symbol": SYMBOL, "instrument_id": item["instrumentId"],
                "verification": verification,
                "exchange": item.get("internalExchangeName"),
                "instrument_type": item.get("instrumentType"),
                "instrument_type_id": item.get("instrumentTypeID"),
                "display_name": item.get("displayname"),
                "is_delisted": item.get("isDelisted"),
                "is_hidden_from_client": item.get("isHiddenFromClient"),
                "is_currently_tradable": item.get("isCurrentlyTradable"),
                "is_buy_enabled": item.get("isBuyEnabled"),
                "current_rate": item.get("currentRate"),
                "unverified_fields": unverified_fields(item),
                "rejection_reason": rejection,
                "observed_at": datetime.now(timezone.utc).isoformat(),
                "conflicts_with_protected_baseline": conflict, "source": "eToro v1 search",
                "authorization": authorization_id}
    Path(evidence_path).write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    _outcome(budget_path, "CONFLICT" if result == "BASELINE_CONFLICT_REJECTED" else result)
    return {**base, "http_status": 200,
            **{k: v for k, v in evidence.items() if k != "observed_at"}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SD-050 one-shot MSFT eToro instrument lookup")
    parser.add_argument("--confirm-sd050-owner-authorization", action="store_true")
    parser.add_argument("--authorization-id", default=AUTHORIZATION_ID,
                        help="owner authorization id; each id has its own one-attempt budget")
    parser.add_argument("--db", default="data/etoro_demo.sqlite3")
    parser.add_argument("--evidence", default="data/sd050-msft-instrument.json")
    args = parser.parse_args(argv)
    if not args.confirm_sd050_owner_authorization:
        parser.error("requires --confirm-sd050-owner-authorization; nothing sent")
    env = {**{k: v for k, v in os.environ.items() if k in DEMO_PAIR_NAMES + LEGACY_NAMES},
           **load_local_credentials()}
    try:
        budget = budget_path_for(args.authorization_id)
        result = run_once(env=env, db_path=args.db, budget_path=budget,
                          evidence_path=args.evidence, authorization_id=args.authorization_id)
    except Exception as exc:  # preflight refusals: nothing sent
        print(json.dumps({"authorization": args.authorization_id, "status": "PREFLIGHT_REFUSED",
                          "reason": type(exc).__name__ + ": " + str(exc),
                          "http_attempts_consumed": None}, indent=2))
        return 5
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "RESOLVED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
