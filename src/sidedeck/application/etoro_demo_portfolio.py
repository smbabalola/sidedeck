"""Local, owner-run eToro DEMO portfolio read and reconciliation (read-only).

Inert unless ``--confirm-owner-demo-read`` is given. Reads ``ETORO_API_KEY`` and
``ETORO_USER_KEY`` from the process environment (load them yourself; this
command never opens ``.env``). Makes exactly one GET to the Demo portfolio
endpoint, then prints a SAFE summary: statuses and counts only, no balances,
P&L values, position/instrument/order IDs or account identifiers.
Never run in CI. No order capability exists.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone

from sidedeck.domain.etoro_demo import parse_demo_portfolio
from sidedeck.domain.etoro_demo_books import DemoReconciliation, reconcile_demo
from sidedeck.infrastructure.etoro_demo_client import EtoroDemoAccessError, EtoroDemoReadClient
from sidedeck.infrastructure.etoro_demo_store import EtoroDemoStore


def safe_summary(report: DemoReconciliation, *, request_id: str,
                 baseline_count: int) -> dict[str, object]:
    """Counts and statuses only; safe to paste or log."""
    return {
        "request_id": request_id, "api_requests_made": 1, "orders_submitted": 0,
        "execution_enabled": report.execution_enabled, "status": report.status,
        "observed_at": report.observed_at.isoformat(), "baseline_positions": baseline_count,
        "discrepancy_count": len(report.discrepancies),
        "available_cash_usd_status": report.available_cash_usd.status,
        "books": {book: {"positions": len(view.position_ids),
                         "unrealized_pnl_status": view.unrealized_pnl.status,
                         "allocation_status": view.allocation_status}
                  for book, view in report.books.items()},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only eToro DEMO portfolio reconciliation")
    parser.add_argument("--confirm-owner-demo-read", action="store_true")
    parser.add_argument("--db", required=True, help="local SideDeck SQLite file (git-ignored)")
    parser.add_argument("--capture-baseline", action="store_true",
                        help="record currently open Demo positions as the unattributed baseline")
    parser.add_argument("--usd-currency-id", type=int, default=None,
                        help="owner-confirmed accountCurrencyId for USD; otherwise cash is UNAVAILABLE")
    args = parser.parse_args(argv)
    if not args.confirm_owner_demo_read:
        parser.error("requires --confirm-owner-demo-read (one read-only Demo GET); nothing sent")
    api_key, user_key = os.environ.get("ETORO_API_KEY"), os.environ.get("ETORO_USER_KEY")
    if not api_key or not user_key:
        parser.error("ETORO_API_KEY and ETORO_USER_KEY must be set in the environment; nothing sent")
    store = EtoroDemoStore(args.db)
    try:
        payload, request_id = EtoroDemoReadClient(api_key=api_key, user_key=user_key) \
            .read_demo_portfolio()
    except EtoroDemoAccessError as exc:
        print(json.dumps({"api_requests_made": 1, "orders_submitted": 0,
                          "classification": exc.classification, "http_status": exc.http_status,
                          "cf_ray": exc.cf_ray, "request_id": exc.request_id}))
        return 1
    now = datetime.now(timezone.utc)
    snapshot = parse_demo_portfolio(payload, observed_at=now)
    if args.capture_baseline:
        store.capture_baseline(snapshot)
    if not store.baseline_captured():
        parser.error("no Demo baseline captured yet; rerun with --capture-baseline")
    baseline = store.baseline()
    report = reconcile_demo(snapshot, baseline=baseline, attributions=store.attributions(),
                            now=now, usd_currency_id=args.usd_currency_id)
    print(json.dumps(safe_summary(report, request_id=request_id, baseline_count=len(baseline)),
                     indent=2))
    return 0 if report.status == "MATCHED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
