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

- [x] **A. Local environment preflight:** on `feat/p2-agent-adapters`, the ignored `.env` was inspected by variable name/presence only; no values were printed. Ollama was reachable at localhost with installed models. The project venv had no upstream runtime or provider SDKs. `SideDeck-Blueprint/` remained untracked and untouched.
- [ ] **B. Runtime wiring:** optional isolated installation of the **licensed, pinned TradingAgents upstream** with licence notices and dependency audit, avoiding source vendoring when not needed. Verify the documented `TradingAgentsGraph.propagate(...)` interface matches the pinned version; if not, reconcile code and report. The currently committed `TradingAgentsProposalAdapter` is CODE_READY only.
- [x] **C. Provider tests:** added `python -m sidedeck.smoke check-providers` and `python -m sidedeck.smoke run --provider ollama|nvidia|openai`, requiring `--allow-network-model-test`. The default path and CI are network-free; redacted evidence is written under ignored `results/`.
- [x] **D. Controlled genuine model call:** one local Ollama request used only synthetic AAPL context at the fixture cutoff. Redacted evidence records provider inference separately from graph execution; the result is `PROVIDER_ONLY`, not a historical backtest or upstream graph claim.
- [ ] **E. Normalize proposal safely:** convert output to SideDeck validated BUY/SELL/HOLD envelope; require explicit size, stop, invalidation for executable trades; if absent, log HOLD/REJECT. SideDeck-only risk gate applies; simulated local orders may be enabled in a **clearly separate** opt-in fixture demonstration, never a broker call.
- [x] **F. Tests and tracking:** provider guard, malformed-output and redacted-evidence tests run offline. Statuses for this smoke are `UPSTREAM_IMPORT_VERIFIED=false`, `LLM_RESPONSE_VERIFIED=true`, `TRADINGAGENTS_GRAPH_RUN_VERIFIED=false`; exact evidence is in ignored `results/real_agent_smoke.json` and the committed report/TODO updates.

## Stop points

Stop the external-provider test only if local models are unavailable, selected credentials/permissions are missing, provider billing policy is unclear, or upstream forces uncontrolled/unsafe market-data calls. Continue safe code/test/documentation tasks. Do **not** stop for routine implementation approvals.

## Working local demo commands (already verified by owner)

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m sidedeck.demo run
Start-Process ".\results\dashboard.html"
```

Use `reset-fixture` **only** when explicitly restarting a known disposable results directory. The reported `--reset` argument is not supported by the currently committed CLI.

## Recorded smoke result

- 2026-10-18, provider `ollama`, model `llama3.2:3b`, one local request, 56 output tokens, approximately 19.3 seconds.
- SideDeck normalization produced a structured envelope accepted by the proposal gateway. No executable proposal was sent to a simulator or broker; the run was simulation-only and made zero broker calls.
- The upstream graph was not run. Installing its pinned dependency set in a disposable temporary venv did not complete within the bounded setup attempt, so upstream import and graph execution remain unverified.

**Interpretation of user screenshot:** the existing browser dashboard is an unstyled engineering table. It is functional but not the final product user experience. Improve presentation separately from genuine model-run verification.
