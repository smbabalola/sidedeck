"""Hard-coded Alpaca PAPER POST request builder; networking stays OFF.

Prepares only limit/DAY, long-only stock/ETF order requests from a SideDeck
risk-approved PaperOrderDraft. This module does *not* load secrets, submit
requests or offer a send() method. A real transport will require a separately
approved broker-write integration and durable one-shot outbox dispatcher.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import json
import re
from typing import Literal
from urllib.request import Request

from .alpaca_paper import APPROVED_SYMBOLS
from .paper_desk import BROKER_KEY_SLOTS, PaperDeskError, PaperOrderDraft

_ORDER_ID = re.compile(r"sd-(?:ta|ai)-[a-f0-9]{32}\Z")
MAX_NOTIONAL_USD = Decimal("1000")


@dataclass(frozen=True)
class PaperPostPreview:
    url: Literal["https://paper-api.alpaca.markets/v2/orders"]
    method: Literal["POST"]
    body: dict[str, str | bool]
    owner_authorized: Literal[False] = False
    network_enabled: Literal[False] = False


def validate_paper_post_draft(draft: PaperOrderDraft) -> None:
    """Validate SideDeck's exact risk-gated draft, not a generic AI payload."""
    if (draft.portfolio_id not in BROKER_KEY_SLOTS
        or BROKER_KEY_SLOTS[draft.portfolio_id] != draft.key_slot):
        raise PaperDeskError("PAPER order would cross strategy account")
    if not _ORDER_ID.fullmatch(draft.client_order_id):
        raise PaperDeskError("PAPER client order id is not SideDeck owned")
    symbol = draft.symbol
    if symbol not in APPROVED_SYMBOLS:
        raise PaperDeskError("paper order symbol not in approved stock/ETF universe")
    if draft.side not in ("buy", "sell"):
        raise PaperDeskError("unsupported order direction")
    if draft.submission_enabled:
        raise PaperDeskError("draft must not allow direct broker submission")
    if (not draft.quantity.is_finite() or draft.quantity <= 0
        or draft.quantity != draft.quantity.to_integral_value()):
        raise PaperDeskError("paper order size must be positive whole shares")
    if not draft.limit_price.is_finite() or draft.limit_price <= 0:
        raise PaperDeskError("paper limit price invalid")
    exponent = draft.limit_price.as_tuple().exponent
    if not isinstance(exponent, int) or exponent < -2:
        raise PaperDeskError("paper limit precision must not exceed 2 decimals")
    if draft.quantity * draft.limit_price > MAX_NOTIONAL_USD:
        raise PaperDeskError("paper order exceeds one strategy's USD 1000 allocation")


def build_paper_post_preview(draft: PaperOrderDraft) -> PaperPostPreview:
    """Return a safe-to-display *unsubmitted* JSON POST request contract."""
    validate_paper_post_draft(draft)
    return PaperPostPreview(
        url="https://paper-api.alpaca.markets/v2/orders",
        method="POST",
        body=draft.alpaca_preview(),
    )


def encode_paper_post_request(draft: PaperOrderDraft) -> Request:
    """Prepare an unauthenticated, untransmitted POST Request for contract tests.

    This object deliberately has NO credentials, auth headers or submit
    functionality. It must never be passed to a real network opener.
    """
    preview = build_paper_post_preview(draft)
    return Request(
        preview.url,
        method=preview.method,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        data=json.dumps(preview.body, sort_keys=True, separators=(",", ":")).encode(),
    )
