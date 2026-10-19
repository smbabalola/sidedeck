"""Single offline-compatible readiness workflow for SideDeck paper account."""
from __future__ import annotations

from dataclasses import dataclass
from sidedeck.application.paper_snapshot import PaperSnapshotAssessment, assess_paper_snapshot
from sidedeck.domain.accounting import PortfolioState
from sidedeck.infrastructure.alpaca_readonly import AlpacaReadOnly


@dataclass(frozen=True)
class ReadinessResult:
    ready_for_review: bool
    reason: str
    snapshot: PaperSnapshotAssessment


def inspect_paper_readiness(
    client: AlpacaReadOnly,
    portfolios: dict[str, PortfolioState],
    *,
    expected_account_id: str,
    dedicated_account: bool = False,
) -> ReadinessResult:
    """Read account/positions/open orders in sequence; never submits an order.

    A positive result merely means a snapshot appears internally consistent;
    it does NOT authorize paper order execution or certify atomicity.
    """
    snapshot = assess_paper_snapshot(
        client, portfolios,
        expected_account_id=expected_account_id,
        dedicated_account=dedicated_account,
    )
    return ReadinessResult(
        ready_for_review=snapshot.safe_to_attribute,
        reason=snapshot.reason,
        snapshot=snapshot,
    )
