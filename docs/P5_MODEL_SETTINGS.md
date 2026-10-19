# P5 configurable AI models

The P5 research launcher accepts a versioned JSON model-settings file.

Example: `config/p5_models.example.json`. Each portfolio has a default provider/model, plus optional per-role overrides. A canonical SHA-256 fingerprint is included in successful decision reports so later edits do not silently rewrite past configurations.

Use:

```powershell
git switch feat/p5-agent-adapters
git pull --ff-only
.\.venv\Scripts\python.exe -m pytest tests/test_p5_model_config.py tests/test_p5_agents.py tests/test_p5_research_gate.py -q
```

The real launcher additionally requires `--models-config config/p5_models.example.json`, `--tradingagents-python`, `--hedge-fund-python`, and `--hedge-fund-bridge`. It does not run unless both installed upstream runtimes are available. Model selection is per-run, not an AI provider API check. Changes require rerunning the research process with the updated configuration. The example model identifiers are editable illustrations, not a guarantee of current API availability or upstream support.

Currently TradingAgents selects the configured **default** provider/model for both its `deep_think_llm` and `quick_think_llm` stages. Role overrides are validated and represented but are **not** automatically mapped to upstream role-specific model settings. The independent AI Hedge Fund runtime remains blocked until a verified no-trade JSON bridge is developed. Both bridges are opt-in and no credentials or external models are used in CI.

No execution or order authorization is provided by this feature. Existing broker execution remains disabled. Do not treat a research decision as an executable order.
