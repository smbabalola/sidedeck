"""Offline-compatible P3 acceptance gate, with no broker order functionality."""
from __future__ import annotations

from dataclasses import dataclass
from sidedeck.application.paper_readiness import inspect_paper_readiness
from sidedeck.domain.accounting import PortfolioState
from sidedeck.infrastructure.alpaca_readonly import AlpacaReadOnly


@dataclass(frozen=True)
class P3Acceptance:
    approved: bool
    reason: str
    account_identity_verified: bool
    broker_positions_consistent: bool
    cash_consistent: bool


def assess_p3(
    client: AlpacaReadOnly,
    portfolios: dict[str, PortfolioState],
    *,
    expected_account_id: str,
    dedicated_account: bool,
) -> P3Acceptance:
    """Read-only snapshot consistency is not execution authorization."""
    result = inspect_paper_readiness(
        client, portfolios, expected_account_id=expected_account_id,
        dedicated_account=dedicated_account,
    )
    snap = result.snapshot
    return P3Acceptance(
        approved=result.ready_for_review,
        reason=result.reason,
        account_identity_verified=snap.account_verified,
        broker_positions_consistent=snap.positions_match.matched,
        cash_consistent=snap.balance_consistent,
    )
