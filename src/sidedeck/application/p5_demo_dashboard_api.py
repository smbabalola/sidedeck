"""Loopback-only, read-only dashboard API for saved eToro Demo baseline metadata.

No eToro HTTP calls, credentials, monetary values, raw IDs, or database writes.
The captured baseline is historical evidence, NOT a fresh reconciliation.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


def baseline_summary(db_path: str) -> dict[str, Any]:
    path = Path(db_path).resolve(strict=True)
    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    try:
        row = db.execute(
            "SELECT captured_at, position_count FROM etoro_demo_baseline_capture "
            "WHERE capture_id=1"
        ).fetchone()
        if row is None:
            return {"baseline_status": "NOT_CAPTURED", "captured_at": None,
                    "protected_positions": None}
        captured = datetime.fromisoformat(row[0])
        if captured.tzinfo is None or type(row[1]) is not int or row[1] < 0:
            raise ValueError("invalid saved baseline")
        count = db.execute("SELECT count(*) FROM etoro_demo_baseline").fetchone()[0]
        if count != row[1]:
            raise ValueError("baseline count mismatch")
        return {"baseline_status": "CAPTURED", "captured_at": captured.isoformat(),
                "protected_positions": count}
    finally:
        db.close()


def read_refresh(path: str | None, *, now: datetime | None = None) -> dict[str, Any] | None:
    if not path:
        return None
    target = Path(path)
    if not target.is_file() or target.is_symlink():
        return None
    try:
        if target.stat().st_size > 8192:
            return None
        data = json.loads(target.read_text(encoding="utf-8"))
        if (data.get("schema_version") != 1
                or data.get("source") != "OWNER_AUTHORIZED_DEMO_READ"
                or data.get("execution_enabled") is not False
                or data.get("reconciliation_status") not in ("MATCHED", "DISCREPANCY")
                or not isinstance(data.get("books"), list)
                or len(data["books"]) != 3):
            return None
        observed = datetime.fromisoformat(data["observed_at"])
        current = now or datetime.now(timezone.utc)
        if observed.tzinfo is None or not timedelta(0) <= current - observed <= timedelta(minutes=5):
            return None
        # Strict field allowlist: never emit arbitrary persisted values into browser JSON.
        return {
            "observed_at": observed.isoformat(),
            "reconciliation_status": data["reconciliation_status"],
            "discrepancy_count": data["discrepancy_count"] if type(data.get("discrepancy_count")) is int and data["discrepancy_count"] >= 0 else None,
            "available_cash_usd_status": data["available_cash_usd_status"] if data.get("available_cash_usd_status") in ("AVAILABLE", "UNAVAILABLE") else "UNAVAILABLE",
            "unrealized_pnl_status": data["unrealized_pnl_status"] if data.get("unrealized_pnl_status") in ("AVAILABLE", "UNAVAILABLE") else "UNAVAILABLE",
            "books": [
                {"id": book, "positions": next((v["positions"] for v in data["books"] if isinstance(v, dict) and v.get("id") == book and type(v.get("positions")) is int and v["positions"] >= 0), None),
                 "allocation_status": "NOT_ALLOCATED"}
                for book in ("etoro-demo:tradingagents", "etoro-demo:ai-trading", "etoro-demo:unattributed")
            ],
        }
    except (OSError, ValueError, KeyError, TypeError):
        return None


def dashboard_summary(db_path: str, snapshot_path: str | None = None, *, now: datetime | None = None) -> dict[str, Any]:
    baseline = baseline_summary(db_path)
    fresh = read_refresh(snapshot_path, now=now)
    return {"schema_version": 1, "source": "LOCAL_BASELINE_ONLY",
            **baseline, "fresh_snapshot": fresh, "reconciliation_status": "NOT_CURRENT",
            "discrepancy_count": None, "available_cash_usd_status": "UNAVAILABLE",
            "unrealized_pnl_status": "UNAVAILABLE", "execution_enabled": False,
            "books": [
                {"id": "etoro-demo:tradingagents", "positions": None, "allocation_status": "NOT_ALLOCATED"},
                {"id": "etoro-demo:ai-trading", "positions": None, "allocation_status": "NOT_ALLOCATED"},
                {"id": "etoro-demo:unattributed", "positions": baseline["protected_positions"],
                 "allocation_status": "NOT_ALLOCATED"},
            ]}


def make_handler(db_path: str, snapshot_path: str | None = None) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if (self.headers.get("Host") not in ("127.0.0.1:8765", "localhost:8765")
                    or urlsplit(self.path).path != "/api/demo/summary"
                    or urlsplit(self.path).query):
                self.send_error(404)
                return
            try:
                data = dashboard_summary(db_path, snapshot_path)
                payload = json.dumps(data).encode("utf-8")
                status = 200
            except (OSError, sqlite3.Error, ValueError):
                payload = b'{"error":"BASELINE_UNAVAILABLE"}'
                status = 503
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_POST(self) -> None:
            self.send_error(405)

        def log_message(self, format: str, *args: Any) -> None:
            pass

    return Handler


def main() -> int:
    p = argparse.ArgumentParser(description="Local-only read-only eToro baseline summary")
    p.add_argument("--db", required=True)
    p.add_argument("--snapshot", default=None)
    a = p.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", 8765), make_handler(a.db, a.snapshot))
    print("SideDeck baseline API listening on 127.0.0.1:8765 (read-only)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
