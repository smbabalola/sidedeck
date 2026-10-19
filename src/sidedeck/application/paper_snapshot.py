"""Fail-closed read-only account inspection; does not mutate experiment portfolios."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sidedeck.application.account_identity import verify_side_deck_paper_account
from sidedeck.application.reconciliation import ReconciliationReport, reconcile_positions
from sidedeck.domain.accounting import PortfolioState
from sidedeck.infrastructure.alpaca_readonly import AlpacaReadOnly, PaperAccount


@dataclass(frozen=True)
class PaperSnapshotAssessment:
    account: PaperAccount
    positions_match: ReconciliationReport
    account_verified: bool
    balance_consistent: bool
    safe_to_attribute: bool
    reason: str


def assess_paper_snapshot(
    client: AlpacaReadOnly,
    portfolios: dict[str, PortfolioState],
    *,
    expected_account_id: str,
    dedicated_account: bool = False,
    no_open_orders_verified: bool = False,
) -> PaperSnapshotAssessment:
    """No paper broker state is assigned to an internal experiment by inference.

    Alpaca equity can include unrealized P&L, and its account may have extra funds,
    other positions or open orders. A matching holdings snapshot alone cannot
    establish strategy capital segregation, or authorize orders.
    """
    account = client.account()
    identity = verify_side_deck_paper_account(
        account, expected_account_id=expected_account_id
    )
    report = reconcile_positions(portfolios, client.positions())
    aggregate_internal_cash = sum((state.cash for state in portfolios.values()), Decimal("0"))
    balance_consistent = account.cash == aggregate_internal_cash
    if not identity.verified:
        reason = identity.reason
    elif not report.matched:
        reason = "position_mismatch"
    elif not balance_consistent:
        reason = "cash_mismatch_or_unattributed_funds"
    elif not dedicated_account:
        reason = "account_dedication_unverified"
    elif not no_open_orders_verified:
        reason = "open_orders_unverified"
    else:
        reason = "read_only_snapshot_consistent"
    safe = (identity.verified and report.matched and balance_consistent
            and dedicated_account and no_open_orders_verified)
    return PaperSnapshotAssessment(
        account, report, identity.verified, balance_consistent, safe, reason
    )
