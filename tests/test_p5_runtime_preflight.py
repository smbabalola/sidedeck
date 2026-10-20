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


def test_local_sec_fundamentals_remove_financial_datasets_requirement(monkeypatch, tmp_path):
    monkeypatch.setattr(importlib.util, "find_spec", lambda _name: object())
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-only")
    monkeypatch.delenv("FINANCIAL_DATASETS_API_KEY", raising=False)
    path = tmp_path / "sec.json"
    path.write_text("{}", encoding="utf-8")
    result = assess_local_runtime("ai-trading", "anthropic", fundamentals_json=str(path))
    assert result["fundamentals_source"] == "LOCAL_SEC_FILE"
    assert result["fundamentals_credential"] == "NOT_REQUIRED"
    assert result["fundamentals_file"] == "FOUND"
    assert result["offline_preflight"] == "READY_TO_ATTEMPT"


def test_missing_local_fundamentals_file_blocks(monkeypatch, tmp_path):
    monkeypatch.setattr(importlib.util, "find_spec", lambda _name: object())
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-only")
    monkeypatch.setenv("FINANCIAL_DATASETS_API_KEY", "test-only")
    result = assess_local_runtime(
        "ai-trading", "anthropic", fundamentals_json=str(tmp_path / "absent.json"),
    )
    assert result["fundamentals_file"] == "MISSING"
    assert result["offline_preflight"] == "BLOCKED"


def test_tradingagents_rejects_local_buffett_fundamentals(tmp_path):
    import pytest
    with pytest.raises(ValueError, match="AI Hedge Fund"):
        assess_local_runtime("tradingagents", "openai", fundamentals_json=str(tmp_path))


def test_credentials_not_exposed(monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", lambda _name: object())
    monkeypatch.setenv("OPENAI_API_KEY", "super-secret-test")
    result = assess_local_runtime("tradingagents", "openai")
    assert result["offline_preflight"] == "READY_TO_ATTEMPT"
    assert "super-secret-test" not in str(result)
