"""Run and inspect a dedicated persistent SideDeck PAPER ledger fixture.

NO Alpaca credentials, network, real broker acknowledgments or paper orders.
Uses only results/paper_outbox_fixture.sqlite3 (a separate tagged DB).
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from html import escape
import json
from pathlib import Path
from typing import Any

from sidedeck.domain.contracts import MarketSnapshot, PriceType, Session, Side, TradeIntent
from sidedeck.domain.paper_desk import PaperFillEvidence
from sidedeck.domain.paper_outbox import DurablePaperDesk

AT = datetime(2026, 1, 5, 21, tzinfo=timezone.utc)
LOCAL_DB = Path("results/paper_outbox_fixture.sqlite3")


def run_offline(db_path: Path = LOCAL_DB) -> dict[str, Any]:
    db = DurablePaperDesk(db_path)
    db.initialize(opened_at=AT - timedelta(minutes=1))
    before = db.snapshot()
    if not any(v["orders"] for v in before["strategies"].values()):
        market = MarketSnapshot(
            instrument_id="US:AAPL", ticker="AAPL", provider="FIXTURE_ONLY",
            price_type=PriceType.EOD_CLOSE, price=Decimal("100"),
            market_timestamp=AT, ingestion_timestamp=AT,
            session=Session.CLOSED, quality="FIXTURE_NOT_REAL_MARKET_DATA",
        )
        for name in ("tradingagents", "ai-trading"):
            intent = TradeIntent(
                experiment_id="paper-outbox-fixture", portfolio_id=name,
                strategy_id=f"{name}-test-proposal", instrument_id="US:AAPL",
                side=Side.BUY, quantity=Decimal("1"),
                rationale="fixture only; no broker", model_revision="fixture-no-llm",
                decision_timestamp=AT, data_as_of=AT,
                stop_price=Decimal("95"), invalidation="synthetic stop",
            )
            draft = db.prepare(intent, market, marks={"US:AAPL": market})
            if name == "tradingagents":
                # This is synthetic evidence from local fixtures, not
                # confirmation an Alpaca order was ever submitted/filled.
                db.acknowledge(draft.client_order_id, broker_order_id="FIXTURE-ORDER")
                db.reconcile_fill(PaperFillEvidence(
                    client_order_id=draft.client_order_id,
                    broker_order_id="FIXTURE-ORDER",
                    broker_fill_id="FIXTURE-FILL",
                    portfolio_id=draft.portfolio_id,
                    key_slot=draft.key_slot,
                    symbol=draft.symbol,
                    side=draft.side,
                    quantity=Decimal("1"),
                    price=Decimal("100"),
                    fee=Decimal("0"),
                    occurred_at=AT + timedelta(minutes=1),
                ))
    # Reopen to demonstrate state survives across independent processes.
    report = DurablePaperDesk(db_path).snapshot()
    return {
        "mode": "LOCAL_FIXTURE_NO_ALPACA",
        "provider_requests": 0,
        "paper_orders_submitted": 0,
        "fake_fill_count": 1,
        "result": report,
    }


def to_html(report: dict[str, Any]) -> str:
    fragments: list[str] = []
    strategies: dict[str, Any] = report["result"]["strategies"]
    for portfolio, state in strategies.items():
        orders = state["orders"]
        order_rows = "".join(
            "<li>" + escape(o["side"].upper()) + " " + escape(o["symbol"]) +
            " — " + escape(o["state"]) + " — fixture filled qty " +
            escape(o["filled_quantity"]) + "</li>" for o in orders
        )
        positions = ", ".join(
            escape(symbol) + ": " + escape(qty)
            for symbol, qty in state["positions"].items()
        ) or "None"
        fragments.append(
            "<section><h2>" + escape(portfolio) + "</h2><p>Key slot: <code>" +
            escape(state["key_slot"]) + "</code></p><p>Local cash: $" +
            escape(state["cash"]) + "</p><p>Local positions: " + positions +
            "</p><ul>" + order_rows + "</ul></section>"
        )
    return """<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>SideDeck Persistent Paper Journal Fixture</title>
<style>body{background:#0c1727;color:#e2e8f0;font:15px system-ui;margin:3rem auto;
max-width:1100px;padding:0 1rem}.warning{border:2px solid #edac45;background:#332610;
color:#ffe7b7;padding:1.2rem;border-radius:10px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(310px,1fr));gap:18px}
section{border:1px solid #344256;padding:24px;border-radius:12px;background:#162439}
h2{margin-top:0}code{color:#93c5fd}</style></head><body>
<h1>SideDeck Persistent Paper Portfolio Review</h1>
<div class="warning"><strong>OFFLINE FIXTURE — NOT REAL ALPACA DATA.</strong>
Simulated local broker acknowledgment and fake fill for recovery testing only.
No provider account accessed, no Alpaca paper orders submitted, no real money.
The broker kill switch remains engaged.</div><div class="grid">""" + "".join(
        fragments
    ) + "</div></body></html>"


def main() -> int:
    parser = argparse.ArgumentParser(description="Persistent SideDeck paper journal demonstration")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.dry_run:
        parser.error("--dry-run required; this command never connects to Alpaca")
    report = run_offline()
    html_path = LOCAL_DB.parent / "paper_outbox_fixture.html"
    json_path = LOCAL_DB.parent / "paper_outbox_fixture.json"
    html_path.write_text(to_html(report), encoding="utf-8")
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "mode": report["mode"],
        "provider_requests": 0,
        "paper_orders_submitted": 0,
        "persistent_file": str(LOCAL_DB),
        "html": str(html_path),
        "json": str(json_path),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
