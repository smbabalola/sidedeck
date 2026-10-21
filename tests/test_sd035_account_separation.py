import json

import pytest

from sidedeck.application.sd035_account_separation import (
    SeparationError, compare_identities, reserve_attempt, validate_account,
)


@pytest.mark.parametrize(("left", "right", "expected"), [
    ("a", "b", "DISTINCT"), ("a", "a", "SAME"), (None, "a", "UNVERIFIED"),
])
def test_identity_comparison_is_exact_and_fail_closed(left, right, expected):
    assert compare_identities(left, right) == expected


def test_account_identity_contract_rejects_missing_or_non_object():
    assert validate_account({"id": "account"}) == "account"
    assert validate_account({"id": ""}) is None
    assert validate_account({"status": "ACTIVE"}) is None
    assert validate_account([]) is None


def test_budget_is_pair_scoped_atomic_and_non_replayable(tmp_path):
    path = str(tmp_path / "budget.sqlite3")
    reserve_attempt(path, "A")
    reserve_attempt(path, "B")
    with pytest.raises(SeparationError, match="exhausted"):
        reserve_attempt(path, "A")
    with pytest.raises(SeparationError, match="exhausted"):
        reserve_attempt(path, "B")


def test_malformed_and_http_results_never_emit_identity():
    assert compare_identities(validate_account({"id": None}), validate_account({"id": "x"})) == "UNVERIFIED"
    assert "account-secret" not in json.dumps({"comparison": compare_identities(None, "account-secret")})
