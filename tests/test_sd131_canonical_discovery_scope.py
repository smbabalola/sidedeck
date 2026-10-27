"""SD-120 credential-name binding stays in the *signed* discovery scope."""
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sidedeck.application.sd077_data_authorization import AuthorizationRefused
from sidedeck.application.sd120_etoro_five_minute import (
    check_scope, draft_authorization, main,
)

NOW = datetime(2026, 10, 27, 11, 0, tzinfo=UTC)
CANONICAL_API = "ETORO_DEMO_TRADE_API_KEY"
CANONICAL_USER = "ETORO_DEMO_TRADE_USER_KEY"


def test_custom_demo_pair_is_bound_to_signed_scope() -> None:
    auth = draft_authorization(
        NOW, owner_terms_reviewed=True,
        api_key_env=CANONICAL_API, user_key_env=CANONICAL_USER,
    )
    check_scope(auth, api_key_env=CANONICAL_API, user_key_env=CANONICAL_USER)
    with pytest.raises(AuthorizationRefused, match="scope"):
        check_scope(auth, api_key_env="ETORO_API_KEY", user_key_env="ETORO_USER_KEY")
    assert auth.max_requests == 9
    assert auth.max_retries == 0
    assert "ETORO_DEMO_TRADE_API_KEY" in auth.canonical().decode("utf-8")


def test_legacy_default_draft_still_has_locked_old_scope() -> None:
    auth = draft_authorization(NOW, owner_terms_reviewed=True)
    check_scope(auth, api_key_env="ETORO_API_KEY", user_key_env="ETORO_USER_KEY")
    with pytest.raises(AuthorizationRefused):
        check_scope(auth, api_key_env=CANONICAL_API, user_key_env=CANONICAL_USER)


def test_cli_draft_custom_names_creates_document_without_gets(tmp_path: Path) -> None:
    output = tmp_path / "signed-scope-draft.json"
    status = main([
        "draft", "--out", str(output), "--owner-confirms-terms-reviewed",
        "--api-key-env", CANONICAL_API, "--user-key-env", CANONICAL_USER,
    ])
    assert status == 0
    payload = output.read_text(encoding="utf-8")
    assert CANONICAL_API in payload and CANONICAL_USER in payload
    assert "market-data" not in output.name
