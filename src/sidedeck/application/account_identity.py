"""Explicit, fail-closed paper-account identity verification."""
from __future__ import annotations

from dataclasses import dataclass
from sidedeck.infrastructure.alpaca_readonly import PaperAccount


@dataclass(frozen=True)
class AccountVerification:
    verified: bool
    reason: str


def verify_side_deck_paper_account(
    observed: PaperAccount, *, expected_account_id: str,
) -> AccountVerification:
    """The operator supplies the expected ID independently of the API key."""
    if not expected_account_id.strip():
        return AccountVerification(False, "expected_identity_not_configured")
    if observed.account_id != expected_account_id:
        return AccountVerification(False, "account_identity_mismatch")
    if observed.currency != "USD":
        return AccountVerification(False, "account_currency_mismatch")
    if observed.status != "ACTIVE":
        return AccountVerification(False, "account_not_active")
    if observed.cash < 0 or observed.equity < 0:
        return AccountVerification(False, "negative_account_balance")
    return AccountVerification(True, "paper_identity_verified")
