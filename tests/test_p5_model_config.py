import json

import pytest

from sidedeck.application.p5_model_config import (
    ModelChoice, load_model_settings, model_environment,
)


def example():
    return {
        "revision": "v1",
        "portfolios": {
            "tradingagents": {
                "default": {"provider": "openai", "model": "gpt-4o-mini"},
                "roles": {"manager": {"provider": "openai", "model": "gpt-4o"}},
            },
            "ai-trading": {
                "default": {"provider": "anthropic", "model": "claude-sonnet-4-5"},
                "roles": {},
            },
        },
    }


def test_independent_and_role_specific_model_selection(tmp_path):
    filename = tmp_path / "models.json"
    filename.write_text(json.dumps(example()), encoding="utf-8")
    result = load_model_settings(filename)
    assert result.portfolios["tradingagents"].select("manager").model == "gpt-4o"
    assert result.portfolios["tradingagents"].select("analyst").model == "gpt-4o-mini"
    assert result.portfolios["ai-trading"].select("manager").provider == "anthropic"
    assert len(result.fingerprint) == 64


def test_change_model_updates_fingerprint_without_rewriting_history(tmp_path):
    filename = tmp_path / "models.json"
    data = example()
    filename.write_text(json.dumps(data), encoding="utf-8")
    before = load_model_settings(filename)
    data["portfolios"]["ai-trading"]["default"]["model"] = "claude-opus-4-1"
    filename.write_text(json.dumps(data), encoding="utf-8")
    after = load_model_settings(filename)
    assert before.fingerprint != after.fingerprint
    assert before.portfolios["ai-trading"].default.model == "claude-sonnet-4-5"


@pytest.mark.parametrize("bad", [
    {"provider": "fake", "model": "abc"},
    {"provider": "openai", "model": ""},
    {"provider": "openai", "model": "../secret"},
])
def test_reject_invalid_model(bad):
    with pytest.raises(ValueError):
        ModelChoice(**bad)


def test_no_credentials_in_routing_env():
    choice = ModelChoice("openai", "gpt-4o-mini")
    assert model_environment(choice) == {
        "SIDEDECK_AI_PROVIDER": "openai", "SIDEDECK_AI_MODEL": "gpt-4o-mini",
    }


def test_reject_cross_portfolio_settings(tmp_path):
    data = example()
    del data["portfolios"]["ai-trading"]
    filename = tmp_path / "models.json"
    filename.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        load_model_settings(filename)
