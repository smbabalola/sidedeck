"""Review Alpaca PAPER broker receipts against SideDeck's durable order journal.

No user or broker credentials, no network by default, no ledger mutations:
the caller explicitly injects a paper GET transport and picks an order.
"""

from __future__ import annotations

from datetime import datetime

from .alpaca_paper import AlpacaPaperError, PaperGetTransport
from .alpaca_paper_execution import (
    AlpacaPaperOrderReader, PaperOrderDiscrepancy, compare_paper_order,
)
from .paper_outbox import DurablePaperDesk


class SideDeckPaperReceiptReview:
    """Compare a single locally approved intent against paper read-only data."""

    def __init__(
        self, desk: DurablePaperDesk, transport: PaperGetTransport,
        *, key_slot: str,
    ) -> None:
        self._desk = desk
        self._reader = AlpacaPaperOrderReader(transport, key_slot=key_slot)

    def inspect(
        self, client_order_id: str, *, observed_at: datetime,
    ) -> PaperOrderDiscrepancy:
        draft = self._desk.order_draft(client_order_id)
        order, fills = self._reader.fetch(draft, observed_at=observed_at)
        # Reload the journal *after* reading broker evidence, so the returned
        # comparison sees concurrent fills that may have been persisted.
        snapshot = self._desk.snapshot()
        strategy = snapshot["strategies"].get(draft.portfolio_id)
        if not isinstance(strategy, dict):
            raise AlpacaPaperError("missing local paper strategy")
        rows = strategy.get("orders")
        if not isinstance(rows, list):
            raise AlpacaPaperError("invalid durable paper journal order list")
        return compare_paper_order(draft, order, fills, rows)
