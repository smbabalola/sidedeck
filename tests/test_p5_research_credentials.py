from sidedeck.application.p5_research_credentials import import_research_env


def test_only_research_keys_imported(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("SAXO_ACCESS_TOKEN", raising=False)
    file = tmp_path / ".env"
    file.write_text('OPENAI_API_KEY="testing"\nSAXO_ACCESS_TOKEN=hidden\n', encoding="utf-8")
    result = import_research_env(file)
    assert result == ("OPENAI_API_KEY",)
    assert "SAXO_ACCESS_TOKEN" not in result
    assert "SAXO_ACCESS_TOKEN" not in __import__("os").environ


def test_existing_credential_not_overwritten(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "higher-priority")
    file = tmp_path / ".env"
    file.write_text("OPENAI_API_KEY=from-file\n", encoding="utf-8")
    assert import_research_env(file) == ("OPENAI_API_KEY",)
    assert __import__("os").environ["OPENAI_API_KEY"] == "higher-priority"
