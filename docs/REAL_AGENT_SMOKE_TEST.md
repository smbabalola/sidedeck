# SideDeck — Real TradingAgents Local Smoke-Test Runbook

**Date:** 2026-10-18  
**Source:** Owner personally confirmed on Windows that `python -m sidedeck.demo run` generated the expected two $1,000 synthetic portfolios, and visually opened `results/dashboard.html`. The browser view includes accepted AAPL/MSFT simulated trades, one rejected oversell, and a HOLD. **This establishes local fixture acceptance only, not original upstream TradingAgents execution.**

## Provider authorisation (owner granted in chat)

The owner reports **NVIDIA API, Ollama API/local server, and OpenAI API credentials/configuration in a private local `.env`** and authorises **a small, controlled local smoke test of real model inference**. Prioritise **Ollama** when a local model/server is available, then **NVIDIA API** within the user's existing free allowance (verify allowance, limits and account policy; do not assume free access), then **OpenAI API** only for a very small fallback test.

This authorisation is **only for local TradingAgents research/model verification**, not broker access, eToro, real trading, other services, broad web research by model agents, or unlimited paid usage.

## Security rules — mandatory

1. Never commit, print, upload, log, screenshot, concatenate into prompts or expose any API key, secret or full `.env`. Do not change tracked `.env.example` to contain secrets. `.env` is gitignored. In status/report logs, only show provider enabled/disabled, masked safe metadata and non-sensitive model ID.
2. Codex running locally can inspect the **names and presence of required `.env` variables** without revealing values. If the file is absent in the current working copy, stop the *external test only* and continue safe code development; **do not ask the owner to paste keys into chat**.
3. Key names are not guaranteed. Support configurable `OPENAI_API_KEY`, `NVIDIA_API_KEY` / configured NVIDIA NIM provider naming, and `OLLAMA_HOST` / `OLLAMA_BASE_URL` only when appropriate. Respect actual provider interfaces; do not invent endpoints or model names. An Ollama instance may run locally or as a separately provisioned endpoint.
4. Before any actual paid-provider call, cap test to **one tiny request per provider initially**, fixed low output-token limit, bounded timeout, no retry storm and no concurrent model calls. Record provider/model and token usage/cost estimate *without secrets*. Do not promise an exact $5 maximum unless a provider-side hard spending cap is actually configured. If usage/billing policy is unknown, skip OpenAI and use a no-spend option.
5. Do not access `imranpollob/ai-trading` source or eToro APIs, or place any broker order.
6. Do not install random/unpinned packages or invoke a raw shell command from any model response.

## Implementation and smoke-test sequence (continuous)

- [ ] **A. Local environment preflight:** safely check `git status`, current feature branch, ignored `.env` presence, interpreter/venv, agent package availability and which locally configured providers are actually reachable. Show no key contents. Preserve `SideDeck-Blueprint/` and all ignored files.
- [ ] **B. Runtime wiring:** optional isolated installation of the **licensed, pinned TradingAgents upstream** with licence notices and dependency audit, avoiding source vendoring when not needed. Verify the documented `TradingAgentsGraph.propagate(...)` interface matches the pinned version; if not, reconcile code and report. The currently committed `TradingAgentsProposalAdapter` is CODE_READY only.
- [ ] **C. Provider tests:** implement an explicit opt-in CLI, e.g. `python -m sidedeck.smoke check-providers` and `python -m sidedeck.smoke run --provider ollama|nvidia|openai --dry-run`, with separate owner-enabled `--allow-network-model-test` flag. A `--dry-run` must never call providers. Keep results under ignored local `results/`.
- [ ] **D. Controlled genuine model call:** select an available provider, preferably local Ollama; send **non-sensitive synthetic research context**, one instrument and one clearly identified fixture timestamp. A single LLM response alone proves provider inference, **not that the TradingAgents multi-agent graph executed**; report each independently. If genuine upstream graph cannot be constrained to an approved data snapshot, do **not** claim point-in-time correctness or run a supposed valid historical backtest; either isolate tools/fixtures or mark the test `PROVIDER_ONLY`.
- [ ] **E. Normalize proposal safely:** convert output to SideDeck validated BUY/SELL/HOLD envelope; require explicit size, stop, invalidation for executable trades; if absent, log HOLD/REJECT. SideDeck-only risk gate applies; simulated local orders may be enabled in a **clearly separate** opt-in fixture demonstration, never a broker call.
- [ ] **F. Tests and tracking:** include provider smoke mocks (no network in CI), injected fake-graph timeout, malformed output, cost/time caps, provider-unavailable and untrusted external-data behaviour. Run offline pytest/Ruff/mypy/PostgreSQL CI; record **UPSTREAM_IMPORT_VERIFIED**, **LLM_RESPONSE_VERIFIED**, **TRADINGAGENTS_GRAPH_RUN_VERIFIED** as separate statuses with dated proof. Update `TODO.md`, `docs/INTEGRATION_REPORT.md` and CLI docs with actual outcomes, redacted diagnostic info and exact test results.

## Stop points

Stop the external-provider test only if local models are unavailable, selected credentials/permissions are missing, provider billing policy is unclear, or upstream forces uncontrolled/unsafe market-data calls. Continue safe code/test/documentation tasks. Do **not** stop for routine implementation approvals.

## Working local demo commands (already verified by owner)

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m sidedeck.demo run
Start-Process ".\results\dashboard.html"
```

Use `reset-fixture` **only** when explicitly restarting a known disposable results directory. The reported `--reset` argument is not supported by the currently committed CLI.

**Interpretation of user screenshot:** the existing browser dashboard is an unstyled engineering table. It is functional but not the final product user experience. Improve presentation separately from genuine model-run verification.
