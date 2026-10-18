"""SideDeck paper-order review: offline two-strategy dashboard, no broker I/O."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from html import escape
import json
from pathlib import Path
from typing import Any

from sidedeck.domain.accounting import Ledger, opening_event
from sidedeck.domain.contracts import MarketSnapshot, PriceType, Session, Side, TradeIntent
from sidedeck.domain.paper_desk import SideDeckPaperDesk

AT = datetime(2026, 1, 5, 21, tzinfo=timezone.utc)


def preview() -> dict[str, Any]:
    """Generate fixture order proposals through the real SideDeck risk gate."""
    ledger = Ledger()
    desk = SideDeckPaperDesk()
    snapshot = MarketSnapshot(
        instrument_id="US:AAPL", ticker="AAPL", provider="FIXTURE_ONLY",
        price_type=PriceType.EOD_CLOSE, price=Decimal("100"),
        market_timestamp=AT, ingestion_timestamp=AT,
        session=Session.CLOSED, quality="FIXTURE_NOT_REAL_MARKET_DATA",
    )
    orders: list[dict[str, str | bool]] = []
    for portfolio_id, title in (
        ("tradingagents", "TradingAgents"), ("ai-trading", "AI Trading"),
    ):
        ledger.append(opening_event(portfolio_id, AT - timedelta(minutes=1)))
        intent = TradeIntent(
            experiment_id="paper-desk-fixture",
            portfolio_id=portfolio_id,
            strategy_id=f"{portfolio_id}-fixture",
            instrument_id="US:AAPL", side=Side.BUY, quantity=Decimal("1"),
            rationale="offline display only", model_revision="fixture-no-model",
            decision_timestamp=AT, data_as_of=AT, stop_price=Decimal("95"),
            invalidation="synthetic stop at 95",
        )
        draft, decision = desk.prepare(
            intent, ledger.replay(portfolio_id), snapshot,
            marks={"US:AAPL": snapshot},
        )
        orders.append({
            "strategy": title,
            "portfolio_id": portfolio_id,
            "paper_key_slot": draft.key_slot,
            "capital_usd": "1000",
            "cash_usd": str(ledger.replay(portfolio_id).cash),
            "risk": decision.reason.value,
            "side": draft.side,
            "symbol": draft.symbol,
            "qty": str(draft.quantity),
            "limit_usd": str(draft.limit_price),
            "client_order_id": draft.client_order_id,
            "status": "PREPARED_NOT_SUBMITTED",
            "paper_orders_sent": "0",
        })
    return {
        "mode": "FIXTURE_ONLY",
        "market_data": "FIXTURE / NOT LIVE MARKET DATA",
        "account_binding": "UNVERIFIED",
        "paper_write_enabled": desk.paper_write_enabled,
        "alpaca_api_calls": 0,
        "orders": orders,
    }


def html_review(report: dict[str, Any]) -> str:
    cards: list[str] = []
    for order in report["orders"]:
        labels = (
            ("Alpaca paper key slot", "paper_key_slot"),
            ("SideDeck starting capital", "capital_usd"),
            ("Risk gate", "risk"), ("Side", "side"), ("Ticker", "symbol"),
            ("Quantity", "qty"), ("Limit price USD", "limit_usd"),
            ("Status", "status"), ("Paper orders sent", "paper_orders_sent"),
        )
        rows = "".join(
            "<tr><th>" + escape(label) + "</th><td>" +
            escape(str(order[key])) + "</td></tr>"
            for label, key in labels
        )
        cards.append(
            '<section class="portfolio"><h2>' + escape(str(order["strategy"])) +
            "</h2><table>" + rows + "</table></section>"
        )
    return """<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SideDeck — Paper Order Review (Fixture Only)</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#0b1220;color:#e5e7eb;font:15px system-ui}
main{max-width:1100px;margin:32px auto;padding:0 22px}h1{font-size:28px}
p{line-height:1.5;color:#a7b5cb}.notice{background:#362b1a;border:1px solid #e3ae63;
border-radius:10px;padding:17px;color:#ffe5b9;margin:24px 0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(310px,1fr));gap:18px}
.portfolio{background:#172235;border:1px solid #39475f;padding:20px;border-radius:13px}
h2{margin-top:0}table{width:100%;border-collapse:collapse}tr{border-top:1px solid #334155}
th,td{padding:10px 2px;text-align:left;font-size:13px}th{color:#a2b0c8;font-weight:500}
footer{margin-top:28px;color:#a7b5cb}
</style></head><body><main>
<h1>SideDeck — Paper Portfolio Review</h1>
<p>Two independent USD 1,000 strategy ledgers. SideDeck owns the risk decision.</p>
<div class="notice"><strong>OFFLINE FIXTURE / NOT REAL MARKET DATA.</strong>
No Alpaca API requests or paper trades were placed. Key slots are provisional.
No broker execution or real trading is enabled.</div>
<div class="grid">""" + "".join(cards) + """</div>
<footer>Two strategy previews · Zero API calls · Zero paper orders ·
No real-money trading</footer></main></body></html>"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline SideDeck paper desk preview")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.dry_run:
        parser.error("offline --dry-run is required; paper orders are not enabled")
    report = preview()
    directory = Path("results")
    directory.mkdir(parents=True, exist_ok=True)
    page = directory / "paper_desk_review.html"
    data = directory / "paper_desk_review.json"
    page.write_text(html_review(report), encoding="utf-8")
    data.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "mode": "FIXTURE_ONLY", "orders_sent": 0,
        "alpaca_api_calls": 0, "portfolios": 2,
        "html": str(page), "json": str(data),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
