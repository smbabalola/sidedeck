"""SD-038 one-shot, owner-authorized eToro DEMO baseline re-reconciliation.

Exactly one ``GET /api/v1/trading/info/demo/pnl`` under a persistent,
single-attempt budget that is reserved *before* sending. No retry, redirect,
polling or other endpoint. The protected baseline database is opened
read-only and its bytes are hashed before and after; it is never written.

Output is sanitized: status, counts and booleans only. No credentials,
account/position/order IDs, quantities, prices, balances or raw responses.
Reuses the existing read-only client, strict parser and reconciliation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Protocol

from sidedeck.domain.etoro_demo import EtoroDemoDataError, field_type_issues, parse_demo_portfolio
from sidedeck.domain.etoro_demo_books import (
    UNATTRIBUTED_BOOK, BaselinePosition, EtoroDemoBookError, OrderAttribution, reconcile_demo,
)
from sidedeck.domain.etoro_demo_orders import DEMO_PNL_PATH, require_demo_route
from sidedeck.infrastructure import etoro_demo_client
from sidedeck.infrastructure.etoro_demo_client import EtoroDemoAccessError, EtoroDemoReadClient

AUTHORIZATION_ID = "SD-038"
MAX_ATTEMPTS = 1
EXPECTED_BASELINE_POSITIONS = 4
CREDENTIAL_NAMES = ("ETORO_API_KEY", "ETORO_USER_KEY")
RELEASE = {"etoro_demo_execution_release": "NO_GO", "broker_execution": "DISABLED",
           "live_trading": "PROHIBITED"}


class PreflightError(RuntimeError):
    """A safety precondition failed; no request was sent."""


class DemoReader(Protocol):
    def read_demo_portfolio(self) -> tuple[Any, str]: ...


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_local_credentials(path: str = ".env") -> None:
    """Load only the two approved eToro names into this process; never print values."""
    target = Path(path)
    if not target.is_file() or target.is_symlink():
        return
    for raw in target.read_text(encoding="utf-8").splitlines():
        if "=" not in raw or raw.lstrip().startswith("#"):
            continue
        name, value = raw.split("=", 1)
        if name.strip() in CREDENTIAL_NAMES:
            os.environ.setdefault(name.strip(), value.strip().strip('"\''))


def read_baseline_readonly(db_path: str) -> tuple[tuple[BaselinePosition, ...],
                                                   tuple[OrderAttribution, ...]]:
    """Open the existing baseline strictly read-only; fail closed if anything is off."""
    target = Path(db_path)
    if not target.is_file() or target.is_symlink():
        raise PreflightError("baseline database is missing or not a regular file")
    uri = target.resolve().as_uri() + "?mode=ro"
    try:
        db = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:
        raise PreflightError("baseline database is unreadable") from exc
    try:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        needed = {"etoro_demo_baseline_capture", "etoro_demo_baseline",
                  "etoro_demo_order_attribution"}
        if not needed <= tables:
            raise PreflightError("baseline database lacks the expected tables")
        capture = db.execute("SELECT position_count FROM etoro_demo_baseline_capture").fetchall()
        if len(capture) != 1 or capture[0][0] != EXPECTED_BASELINE_POSITIONS:
            raise PreflightError("baseline capture record is missing or ambiguous")
        rows = db.execute("SELECT position_id, instrument_id, order_id, is_buy, units, opened_at "
                          "FROM etoro_demo_baseline ORDER BY position_id").fetchall()
        attributions = tuple(OrderAttribution(o, b) for o, b in db.execute(
            "SELECT order_id, book_id FROM etoro_demo_order_attribution ORDER BY order_id"))
    except sqlite3.Error as exc:
        raise PreflightError("baseline database is unreadable") from exc
    finally:
        db.close()
    if len(rows) != EXPECTED_BASELINE_POSITIONS:
        raise PreflightError("baseline does not hold exactly the four protected positions")
    baseline = tuple(BaselinePosition(r[0], r[1], r[2], bool(r[3]), Decimal(r[4]),
                                      datetime.fromisoformat(r[5])) for r in rows)
    return baseline, attributions


def _budget(path: str) -> sqlite3.Connection:
    db = sqlite3.connect(path, isolation_level=None)
    db.execute("CREATE TABLE IF NOT EXISTS sd038_budget (singleton INTEGER PRIMARY KEY "
               "CHECK (singleton = 1), authorization_id TEXT NOT NULL, attempts INTEGER NOT NULL, "
               "outcome TEXT NOT NULL, updated_at TEXT NOT NULL)")
    return db


def attempts_consumed(path: str) -> int:
    if not Path(path).is_file():
        return 0
    db = _budget(path)
    try:
        row = db.execute("SELECT attempts FROM sd038_budget WHERE singleton=1").fetchone()
        return 0 if row is None else int(row[0])
    finally:
        db.close()


def reserve_attempt(path: str) -> None:
    """Atomically consume the single authorized attempt before any network activity."""
    db = _budget(path)
    try:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT attempts FROM sd038_budget WHERE singleton=1").fetchone()
        if row is not None and row[0] >= MAX_ATTEMPTS:
            raise PreflightError("SD-038 authorization is exhausted; no request sent")
        db.execute("INSERT INTO sd038_budget VALUES (1, ?, 1, 'RESERVED', ?)",
                   (AUTHORIZATION_ID, datetime.now(timezone.utc).isoformat()))
        db.execute("COMMIT")
    except BaseException:
        if db.in_transaction:
            db.execute("ROLLBACK")
        raise
    finally:
        db.close()


def _record_outcome(path: str, outcome: str) -> None:
    db = _budget(path)
    try:
        db.execute("UPDATE sd038_budget SET outcome=?, updated_at=? WHERE singleton=1",
                   (outcome, datetime.now(timezone.utc).isoformat()))
    finally:
        db.close()


def run_once(*, db_path: str, budget_path: str,
             client_factory: Callable[[str, str], DemoReader] | None = None) -> dict[str, Any]:
    """Preflight, reserve, one GET, reconcile in memory, sanitized summary."""
    require_demo_route("GET", DEMO_PNL_PATH)
    if etoro_demo_client.ALLOWED_PATHS != frozenset({DEMO_PNL_PATH}):
        raise PreflightError("read client allowlist is not the single Demo portfolio path")
    if attempts_consumed(budget_path) >= MAX_ATTEMPTS:
        raise PreflightError("SD-038 authorization is exhausted; no request sent")
    target = Path(db_path)
    baseline, attributions = read_baseline_readonly(db_path)
    before = _sha256(target)
    api_key, user_key = (os.environ.get(name) for name in CREDENTIAL_NAMES)
    if not api_key or not user_key:
        raise PreflightError("ETORO_API_KEY and ETORO_USER_KEY are not available; no request sent")
    factory = client_factory or (lambda a, u: EtoroDemoReadClient(api_key=a, user_key=u))
    client = factory(api_key, user_key)
    reserve_attempt(budget_path)
    base: dict[str, Any] = {"authorization": AUTHORIZATION_ID, "http_attempts_consumed": 1,
                            "endpoint": "GET " + DEMO_PNL_PATH, "orders_submitted": 0, **RELEASE}
    try:
        payload, _request_id = client.read_demo_portfolio()
    except EtoroDemoAccessError as exc:
        _record_outcome(budget_path, f"FAILED:{exc.classification}")
        return {**base, "status": "FAILED_UNVERIFIED", "http_status": exc.http_status,
                "classification": exc.classification,
                "baseline_db_unchanged": _sha256(target) == before}
    observed = datetime.now(timezone.utc)
    issues = field_type_issues(payload)
    if issues:
        _record_outcome(budget_path, "SCHEMA_INVALID")
        return {**base, "status": "FAILED_UNVERIFIED", "http_status": 200,
                "schema_validation": "FAILED", "schema_issue_count": len(issues),
                "baseline_db_unchanged": _sha256(target) == before}
    try:
        snapshot = parse_demo_portfolio(payload, observed_at=observed)
        report = reconcile_demo(snapshot, baseline=baseline, attributions=attributions,
                                now=observed)
    except (EtoroDemoDataError, EtoroDemoBookError):
        _record_outcome(budget_path, "PARSE_FAILED")
        return {**base, "status": "FAILED_UNVERIFIED", "http_status": 200,
                "schema_validation": "FAILED", "baseline_db_unchanged": _sha256(target) == before}
    live = {p.position_id: p for p in snapshot.positions}
    matched = sum(1 for b in baseline if b.position_id in live
                  and BaselinePosition.of(live[b.position_id]) == b)
    baseline_ids = {b.position_id for b in baseline}
    unattributed_extra = sum(1 for p in report.books[UNATTRIBUTED_BOOK].position_ids
                             if p not in baseline_ids)
    mirror = bool(snapshot.mirror_count) or any(p.mirror_id for p in snapshot.positions)
    _record_outcome(budget_path, report.status)
    return {**base, "status": report.status, "http_status": 200, "schema_validation": "PASSED",
            "current_position_count": len(snapshot.positions),
            "protected_baseline_positions": len(baseline),
            "protected_baseline_matched": matched,
            "discrepancy_present": bool(report.discrepancies),
            "discrepancy_count": len(report.discrepancies),
            "unattributed_extra_positions": unattributed_extra,
            "mirror_positions_present": mirror,
            "sidedeck_attributed_positions": sum(
                len(v.position_ids) for k, v in report.books.items() if k != UNATTRIBUTED_BOOK),
            "pending_orders_present": bool(snapshot.pending_orders),
            "baseline_db_unchanged": _sha256(target) == before}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SD-038 one-shot eToro Demo baseline read")
    parser.add_argument("--confirm-sd038-owner-authorization", action="store_true")
    parser.add_argument("--db", default="data/etoro_demo.sqlite3")
    parser.add_argument("--budget", default="data/sd038-auth-budget.sqlite3")
    args = parser.parse_args(argv)
    if not args.confirm_sd038_owner_authorization:
        parser.error("requires --confirm-sd038-owner-authorization; nothing sent")
    load_local_credentials()
    try:
        result = run_once(db_path=args.db, budget_path=args.budget)
    except PreflightError as exc:
        print(json.dumps({"authorization": AUTHORIZATION_ID, "status": "PREFLIGHT_REFUSED",
                          "reason": str(exc), "http_attempts_consumed":
                          attempts_consumed(args.budget), **RELEASE}, indent=2))
        return 5
    print(json.dumps(result, indent=2))
    return {"MATCHED": 0, "DISCREPANCY": 2}.get(result["status"], 1)


if __name__ == "__main__":
    raise SystemExit(main())
