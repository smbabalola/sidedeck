"""Loopback-only, read-only dashboard API for saved eToro Demo baseline metadata.

No eToro HTTP calls, credentials, monetary values, raw IDs, or database writes.
The captured baseline is historical evidence, NOT a fresh reconciliation.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime
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


def dashboard_summary(db_path: str) -> dict[str, Any]:
    baseline = baseline_summary(db_path)
    return {"schema_version": 1, "source": "LOCAL_BASELINE_ONLY",
            **baseline, "reconciliation_status": "NOT_CURRENT",
            "discrepancy_count": None, "available_cash_usd_status": "UNAVAILABLE",
            "unrealized_pnl_status": "UNAVAILABLE", "execution_enabled": False,
            "books": [
                {"id": "etoro-demo:tradingagents", "positions": None, "allocation_status": "NOT_ALLOCATED"},
                {"id": "etoro-demo:ai-trading", "positions": None, "allocation_status": "NOT_ALLOCATED"},
                {"id": "etoro-demo:unattributed", "positions": baseline["protected_positions"],
                 "allocation_status": "NOT_ALLOCATED"},
            ]}


def make_handler(db_path: str) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if (self.headers.get("Host") not in ("127.0.0.1:8765", "localhost:8765")
                    or urlsplit(self.path).path != "/api/demo/summary"
                    or urlsplit(self.path).query):
                self.send_error(404)
                return
            try:
                data = dashboard_summary(db_path)
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
    a = p.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", 8765), make_handler(a.db))
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
