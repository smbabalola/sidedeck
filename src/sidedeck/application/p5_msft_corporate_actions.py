"""Offline MSFT corporate-action evidence for the SD-004 price window."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class CorporateAction:
    kind: str
    effective_date: date
    ratio: str | None
    amount_per_share: Decimal | None
    source_url: str


MSFT_LATEST_SPLIT = CorporateAction(
    kind="split", effective_date=date(2003, 2, 18), ratio="2:1",
    amount_per_share=None,
    source_url="https://news.microsoft.com/source/2003/01/16/microsoft-declares-annual-dividend-and-announces-two-for-one-split-on-common-stock/",
)
MSFT_WINDOW_DIVIDEND = CorporateAction(
    kind="dividend", effective_date=date(2026, 8, 20), ratio=None,
    amount_per_share=Decimal("0.91"),
    source_url="https://news.microsoft.com/source/2026/06/10/microsoft-announces-quarterly-dividend-29/",
)


def verify_msft_window(start: date, end: date) -> dict[str, object]:
    if end < start:
        raise ValueError("corporate-action window must be ordered")
    splits_in_window = start <= MSFT_LATEST_SPLIT.effective_date <= end
    dividends_in_window = [
        action for action in (MSFT_WINDOW_DIVIDEND,)
        if start <= action.effective_date <= end
    ]
    return {
        "status": "VERIFIED" if not splits_in_window else "REVIEW_REQUIRED",
        "split_in_window": splits_in_window,
        "split_basis": "split_adjusted_close",
        "latest_split": MSFT_LATEST_SPLIT,
        "dividends_in_window": tuple(dividends_in_window),
        "dividend_adjustment": "excluded_from_close; Close is not total-return",
    }
