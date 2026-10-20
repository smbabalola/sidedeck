"""Owner-authorized single eToro Demo GET and sanitized, expiring dashboard snapshot.

No background network calls. No raw positions, IDs, payload, credentials or broker
orders are saved. Existing baseline is opened and reconciled, never modified.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sidedeck.domain.etoro_demo import field_type_issues, parse_demo_portfolio
from sidedeck.domain.etoro_demo_books import reconcile_demo
from sidedeck.infrastructure.etoro_demo_client import EtoroDemoReadClient
from sidedeck.infrastructure.etoro_demo_store import EtoroDemoStore


def sanitized_snapshot(payload: Any, store: EtoroDemoStore, *, at: datetime) -> dict[str, Any]:
    if field_type_issues(payload):
        raise ValueError("FIELD_TYPES_INVALID")
    snapshot = parse_demo_portfolio(payload, observed_at=at)
    if not store.baseline_captured():
        raise ValueError("BASELINE_MISSING")
    report = reconcile_demo(snapshot, baseline=store.baseline(),
                            attributions=store.attributions(), now=at)
    result = {
        "schema_version": 1, "source": "OWNER_AUTHORIZED_DEMO_READ",
        "observed_at": at.astimezone(timezone.utc).isoformat(),
        "reconciliation_status": report.status,
        "discrepancy_count": len(report.discrepancies),
        "available_cash_usd_status": report.available_cash_usd.status,
        "unrealized_pnl_status": snapshot.unrealized_pnl().status,
        "execution_enabled": False,
        "books": [
            {"id": name, "positions": len(report.books[name].position_ids),
             "unrealized_pnl_status": report.books[name].unrealized_pnl.status,
             "allocation_status": "NOT_ALLOCATED"}
            for name in ("etoro-demo:tradingagents", "etoro-demo:ai-trading",
                         "etoro-demo:unattributed")
        ],
    }
    # No monetary values until independent real-response value-level acceptance.
    return result


def save_snapshot(path: str, result: dict[str, Any]) -> None:
    destination = Path(path).resolve()
    if not destination.parent.is_dir():
        raise ValueError("snapshot directory does not exist")
    if destination.is_symlink():
        raise ValueError("snapshot symlink refused")
    fd, tmp = tempfile.mkstemp(prefix=".sidedeck-refresh-", dir=str(destination.parent))
    try:
        if os.name != "nt":
            os.chmod(tmp, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(result, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, destination)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def main() -> int:
    p = argparse.ArgumentParser(description="Explicit owner-only eToro Demo read-only refresh")
    p.add_argument("--confirm-owner-demo-read", action="store_true")
    p.add_argument("--db", required=True)
    p.add_argument("--snapshot", required=True)
    args = p.parse_args()
    if not args.confirm_owner_demo_read:
        p.error("explicit owner approval required; no request made")
    key = os.environ.get("ETORO_API_KEY")
    user_key = os.environ.get("ETORO_USER_KEY")
    if not key or not user_key:
        p.error("missing process environment credentials; no request made")
    store = EtoroDemoStore(args.db)
    if not store.baseline_captured():
        p.error("saved baseline required; no request made")
    payload, _ = EtoroDemoReadClient(api_key=key, user_key=user_key).read_demo_portfolio()
    try:
        result = sanitized_snapshot(payload, store, at=datetime.now(timezone.utc))
    except ValueError:
        print("REFRESH=REJECTED; existing dashboard snapshot unchanged")
        return 3
    save_snapshot(args.snapshot, result)
    print("REFRESH=RECORDED; RECONCILIATION=" + result["reconciliation_status"])
    print("NO_ORDERS=TRUE; FINANCIAL_VALUES_WITHHELD=TRUE")
    return 0 if result["reconciliation_status"] == "MATCHED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
