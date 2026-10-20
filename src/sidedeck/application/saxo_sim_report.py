"""Saxo SIM performance report, kept separate from research and Alpaca paper.

Per strategy book: allocation, EUR cash, USD positions, realised/unrealised
P&L, fees, return and reconciliation status. The report never sums across
books or venues. Unrealised P&L needs an explicit USD mark and EUR/USD rate;
without them it is reported as UNAVAILABLE rather than estimated.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path
from typing import Any, Mapping

from sidedeck.domain.sim_accounting import STRATEGY_BOOKS, UNATTRIBUTED_BOOK
from sidedeck.infrastructure.saxo_sim_journal import SimJournalStore

CENT = Decimal("0.01")
SEPARATION_NOTE = ("Saxo SIM results only. Never combined with research portfolios or Alpaca "
                   "paper results; compare side by side only.")


def _money(value: Decimal | None) -> str | None:
    return None if value is None else str(value.quantize(CENT, ROUND_HALF_EVEN))


def sim_performance_report(store: SimJournalStore, *, as_of: datetime,
                           marks_usd: Mapping[str, Decimal] | None = None,
                           fx_usd_per_eur: Decimal | None = None) -> dict[str, Any]:
    if as_of.tzinfo is None:
        raise ValueError("report time must be timezone-aware")
    ledger = store.load_ledger()
    statuses = store.statuses()
    books: list[dict[str, Any]] = []
    for strategy, book in STRATEGY_BOOKS.items():
        state = ledger.replay(book)
        status = statuses.get(book)
        positions = []
        market_value_eur: Decimal | None = Decimal("0")
        for instrument, position in sorted(state.positions.items()):
            mark = (marks_usd or {}).get(instrument)
            value_eur = (position.quantity * mark / fx_usd_per_eur
                         if mark is not None and fx_usd_per_eur else None)
            if value_eur is None:
                market_value_eur = None
            elif market_value_eur is not None:
                market_value_eur += value_eur
            positions.append({
                "instrument_id": instrument, "quantity": str(position.quantity),
                "cost_usd": _money(position.cost_usd), "cost_eur": _money(position.cost_eur),
                "market_value_eur": _money(value_eur),
                "unrealized_pnl_eur": _money(None if value_eur is None
                                             else value_eur - position.cost_eur),
            })
        equity = None if market_value_eur is None else state.cash_eur + market_value_eur
        books.append({
            "strategy_id": strategy, "book_id": book,
            "allocation_eur": _money(state.allocation_eur), "cash_eur": _money(state.cash_eur),
            "fees_eur": _money(state.fees_eur), "realized_pnl_eur": _money(state.realized_pnl_eur),
            "unrealized_pnl_eur": _money(None if market_value_eur is None else market_value_eur
                                         - sum((p.cost_eur for p in state.positions.values()),
                                               Decimal("0"))),
            "equity_eur": _money(equity),
            "return_pct": (None if equity is None or not state.allocation_eur else
                           _money((equity - state.allocation_eur) / state.allocation_eur * 100)),
            "fills": state.fill_count, "positions": positions,
            "book_status": status.status if status else "NOT_OPENED",
            "freeze_scope": status.freeze_scope if status else None,
            "freeze_reason": status.freeze_reason if status else None,
        })
    control = ledger.replay(UNATTRIBUTED_BOOK)
    return {
        "venue": "SAXO_SIM", "account_currency": "EUR", "instrument_currency": "USD",
        "as_of": as_of.astimezone(timezone.utc).isoformat(),
        "marks": "PROVIDED" if marks_usd and fx_usd_per_eur else "UNAVAILABLE",
        "separation": SEPARATION_NOTE, "strategy_books": books,
        "unattributed_control_book": {
            "book_id": UNATTRIBUTED_BOOK, "purpose": "baseline and non-SideDeck activity; no returns",
            "positions": {k: str(v.quantity) for k, v in sorted(control.positions.items())},
        },
        "last_reconciliation": store.last_reconciliation(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline Saxo SIM performance report")
    parser.add_argument("--db", type=Path, required=True)
    args = parser.parse_args(argv)
    if not args.db.is_file():
        parser.error("SIM journal database not found")
    report = sim_performance_report(SimJournalStore(str(args.db)), as_of=datetime.now(timezone.utc))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
