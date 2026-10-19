from decimal import Decimal
from sidedeck.application.account_identity import verify_side_deck_paper_account
from sidedeck.infrastructure.alpaca_readonly import PaperAccount


def account(status="ACTIVE"):
    return PaperAccount(
        account_id="synthetic-account", currency="USD",
        equity=Decimal("1000"), cash=Decimal("1000"), status=status,
    )


def test_matching_explicit_account_id():
    result = verify_side_deck_paper_account(account(), expected_account_id="synthetic-account")
    assert result.verified


def test_wrong_account_id_rejected():
    result = verify_side_deck_paper_account(account(), expected_account_id="other")
    assert result.reason == "account_identity_mismatch"


def test_missing_expected_identity_rejected():
    assert not verify_side_deck_paper_account(account(), expected_account_id=" ").verified


def test_inactive_account_rejected():
    assert verify_side_deck_paper_account(account("INACTIVE"), expected_account_id="synthetic-account").reason == "account_not_active"
