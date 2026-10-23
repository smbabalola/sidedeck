"""Two Alpaca PAPER account identity check for isolated SideDeck strategies.

Explicitly read-only. Account IDs are compared in memory, never returned,
logged, hashed or persisted. Broker positions/orders are not accessed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .alpaca_paper import (
    AlpacaPaperError, AlpacaPaperReadClient, PaperGetTransport, _parse_account,
)

Strategy = Literal["tradingagents", "ai-trading"]


@dataclass(frozen=True)
class PaperAccountPairStatus:
    first_strategy: Strategy
    second_strategy: Strategy
    two_accounts_verified: bool
    both_active: bool
    both_unblocked: bool
    margin_possible: bool
    broker_order_submission_enabled: bool
    outcome: Literal["DISTINCT_ACCOUNTS", "SAME_ACCOUNT", "ACCOUNTS_NOT_READY"]

    # Nothing from the broker identity, account number, positions or key
    # material is returned by this data class.


class DualPaperAccountInspector:
    """Calls exactly one GET /v2/account per credential; no retries or writes."""

    def __init__(self, first: PaperGetTransport, second: PaperGetTransport) -> None:
        self._first = AlpacaPaperReadClient(first)
        self._second = AlpacaPaperReadClient(second)

    @staticmethod
    def _identity(client: AlpacaPaperReadClient) -> tuple[str, bool, bool, bool]:
        raw: Any = client._get("/v2/account", {})
        if not isinstance(raw, dict):
            raise AlpacaPaperError("paper account response must be an object")
        account_id = raw.get("id")
        if not isinstance(account_id, str) or not account_id.strip() or len(account_id) > 200:
            raise AlpacaPaperError("broker account identity is missing or invalid")
        account = _parse_account(raw)
        active = account.status.upper() == "ACTIVE"
        unblocked = not (account.account_blocked or account.trading_blocked)
        margin_possible = account.multiplier > 1
        return account_id, active, unblocked, margin_possible

    def inspect(self) -> PaperAccountPairStatus:
        id1, active1, unblocked1, margin1 = self._identity(self._first)
        id2, active2, unblocked2, margin2 = self._identity(self._second)
        distinct = id1 != id2
        ready = active1 and active2 and unblocked1 and unblocked2
        outcome: Literal["DISTINCT_ACCOUNTS", "SAME_ACCOUNT", "ACCOUNTS_NOT_READY"]
        if not distinct:
            outcome = "SAME_ACCOUNT"
        elif not ready:
            outcome = "ACCOUNTS_NOT_READY"
        else:
            outcome = "DISTINCT_ACCOUNTS"
        return PaperAccountPairStatus(
            first_strategy="tradingagents",
            second_strategy="ai-trading",
            two_accounts_verified=distinct,
            both_active=active1 and active2,
            both_unblocked=unblocked1 and unblocked2,
            margin_possible=margin1 or margin2,
            broker_order_submission_enabled=False,
            outcome=outcome,
        )
