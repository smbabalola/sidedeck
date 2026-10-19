import importlib.util

from sidedeck.application.p5_runtime_preflight import assess_local_runtime


def test_missing_upstream_and_credentials_fail_closed(monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", lambda _name: None)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = assess_local_runtime("tradingagents", "openai")
    assert result["runtime_package"] == "MISSING"
    assert result["model_credential"] == "MISSING"
    assert result["offline_preflight"] == "BLOCKED"


def test_ai_hedge_fund_requires_data_key(monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", lambda _name: object())
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-only")
    monkeypatch.delenv("FINANCIAL_DATASETS_API_KEY", raising=False)
    result = assess_local_runtime("ai-trading", "anthropic")
    assert result["runtime_package"] == "FOUND"
    assert result["fundamentals_credential"] == "MISSING"
    assert result["offline_preflight"] == "BLOCKED"


def test_credentials_not_exposed(monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", lambda _name: object())
    monkeypatch.setenv("OPENAI_API_KEY", "super-secret-test")
    result = assess_local_runtime("tradingagents", "openai")
    assert result["offline_preflight"] == "READY_TO_ATTEMPT"
    assert "super-secret-test" not in str(result)
