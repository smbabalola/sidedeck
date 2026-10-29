"""SD-130 preflight never invokes eToro or displays credentials."""
from pathlib import Path

import pytest

from sidedeck.application.sd042_etoro_credential_roles import POLICY
from sidedeck.application.sd130_demo_credential_preflight import (
    local_demo_preflight, main,
)


def _file(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _canon() -> str:
    # Deliberately fake local-only secret values.
    return "ETORO_DEMO_TRADE_API_KEY=fake_app\nETORO_DEMO_TRADE_USER_KEY=fake_user\n"


def test_canonical_pair_has_no_authority_to_trade(tmp_path: Path) -> None:
    env = _file(tmp_path / ".env", _canon())
    result = local_demo_preflight(str(env), inherited={})
    assert result["credential_config"] == POLICY
    assert result["demo_pair"] == "PRESENT"
    assert result["demo_write_entitlement"] == "UNVERIFIED"
    assert result["broker_route"] == "NOT_RELEASED"
    assert result["orders"] == result["authenticated_requests"] == 0
    assert "fake_" not in repr(result)
    assert str(env) not in repr(result)


def test_legacy_pair_is_refused_without_displaying_values(tmp_path: Path) -> None:
    env = _file(tmp_path / ".env", _canon() +
                "ETORO_API_KEY=obsolete_app\nETORO_USER_KEY=obsolete_user\n")
    result = local_demo_preflight(str(env), inherited={})
    assert result["credential_config"] == "EXTRA_CREDENTIAL_NAMES_REFUSED"
    assert result["legacy_names"] == "PRESENT"
    assert "obsolete_" not in repr(result)


def test_inherited_legacy_key_is_refused_even_with_clean_file(tmp_path: Path) -> None:
    env = _file(tmp_path / ".env", _canon())
    result = local_demo_preflight(str(env), inherited={"ETORO_USER_KEY": "fake"})
    assert result["credential_config"] == "EXTRA_CREDENTIAL_NAMES_REFUSED"


def test_name_collision_is_refused_without_revealing_difference(tmp_path: Path) -> None:
    env = _file(tmp_path / ".env", _canon())
    result = local_demo_preflight(
        str(env), inherited={"ETORO_DEMO_TRADE_USER_KEY": "different_fake"})
    assert result["credential_config"] == "FILE_PROCESS_VALUE_CONFLICT"
    assert result["process_collision"] == "REFUSED"
    assert "different_fake" not in repr(result)


def test_missing_or_symlink_file_never_falls_back_to_process_secrets(
    tmp_path: Path,
) -> None:
    missing = local_demo_preflight(
        str(tmp_path / "missing.env"),
        inherited={"ETORO_DEMO_TRADE_API_KEY": "foo",
                   "ETORO_DEMO_TRADE_USER_KEY": "bar"})
    assert missing["credential_config"] == "MISSING_LOCAL_ENV_FILE"
    env = _file(tmp_path / "real.env", _canon())
    link = tmp_path / "link.env"
    try:
        link.symlink_to(env)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this test platform")
    with pytest.raises(ValueError, match="symlink"):
        local_demo_preflight(str(link), inherited={})


def test_cli_prints_sanitized_result_without_keys(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ETORO_API_KEY", raising=False)
    monkeypatch.delenv("ETORO_USER_KEY", raising=False)
    monkeypatch.delenv("ETORO_DEMO_TRADE_API_KEY", raising=False)
    monkeypatch.delenv("ETORO_DEMO_TRADE_USER_KEY", raising=False)
    env = _file(tmp_path / ".env", _canon())
    assert main(["--env-file", str(env)]) == 0
    captured = capsys.readouterr()
    assert "SINGLE_DEMO_PAIR_OWNER_ACCEPTED" in captured.out
    assert "fake_app" not in captured.out
    assert "fake_user" not in captured.out
    assert "NOT_RELEASED" in captured.out
