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
- [x] **B. Runtime wiring:** the pinned source was installed in a disposable Python 3.12 environment. The first declarative dependency transaction stalled during Windows package installation; targeted wheel installation of the identified graph dependencies completed, and the exact `TradingAgentsGraph` import then succeeded. The environment was not added to the repository.
- [x] **C. Provider tests:** added `python -m sidedeck.smoke check-providers` and `python -m sidedeck.smoke run --provider ollama|nvidia|openai`, requiring `--allow-network-model-test`. The default path and CI are network-free; redacted evidence is written under ignored `results/`.
- [x] **D. Controlled genuine model call:** one local Ollama request used only synthetic AAPL context at the fixture cutoff. Redacted evidence records provider inference separately from graph execution; the result is `PROVIDER_ONLY`, not a historical backtest or upstream graph claim.
- [x] **E. Normalize proposal safely:** the adapter now accepts all upstream five-level ratings and `REVIEW` as audited non-executable signals/HOLD, preserving the rating and requiring final-state provenance. It never fabricates size, stop or invalidation; executable trade dictionaries remain subject to the existing SideDeck gateway and risk gate.
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

## SD-10B result

- `UPSTREAM_IMPORT_VERIFIED=true`: exact `TradingAgentsGraph` import succeeded in the disposable environment after targeted installation of the missing graph wheels.
- `UPSTREAM_GRAPH_INVOKED=true`, `UPSTREAM_GRAPH_RUN_VERIFIED=false`: one minimal `market`-analyst graph invocation was attempted with `llama3.2:3b`, zero debate/risk rounds, one tool round and a 96-token cap.
- `DATA_ISOLATION_VERIFIED=false`: the graph attempted `fc.yahoo.com` cookie/crumb access through its `curl_cffi` Yahoo vendor before reaching a model result. The Python socket guard did not cover that native transport, so the run was stopped and no rating is claimed.
- `PROVIDER_INFERENCE_VERIFIED=true` refers only to the earlier already-recorded provider-only Ollama test; it was not repeated. `EXECUTABLE_PROPOSAL_VALIDATED=false`; no simulator, ledger, order or broker mutation occurred.

**Interpretation of user screenshot:** the existing browser dashboard is an unstyled engineering table. It is functional but not the final product user experience. Improve presentation separately from genuine model-run verification.

## Next focused task — make the *actual* pinned upstream graph run

**Verified 2026-10-18 against pinned upstream GitHub source** `TauricResearch/TradingAgents@e8f5503e9b86d5c2710b0c76b1f686703968c9df`:

- `tradingagents/graph/trading_graph.py`: `TradingAgentsGraph.propagate(company_name, trade_date, asset_type="stock", portfolio=None)` returns `(final_state, signal)`. The signal is **NOT a structured order dict**: it is a five-tier rating `Buy / Overweight / Hold / Underweight / Sell`, or `REVIEW` when unreadable. See `tradingagents/agents/rating.py`, `run_rating` and `RATING_REVIEW`.
- The currently committed `TradingAgentsProposalAdapter.propose` passes that string straight to `normalize_decision`, which accepts dictionaries only. **This is a confirmed integration bug**. Fix before claiming integration. A rating is a **research signal**, not an executable BUY/SELL. Preserve the actual five-tier rating and final-state provenance. Never fabricate size, stop or invalidation to turn it into an order; if no independent documented risk/sizing rule with validated data exists, emit an audited non-executable signal/HOLD/REVIEW.
- `pyproject.toml` at pinned upstream has substantial dependencies (including `langchain`, `langgraph`, `pandas`, `yfinance`). A short bounded pip installation attempt failing to finish **does not establish incompatibility**. Record actual pip error/timeout stage and package, not assumptions; avoid editing SideDeck's pinned main environment.
- Upstream `default_config.py` defaults to vendors including `yfinance`, SEC and news tools and can fetch live or historical external data, with implicit identity resolution via `yfinance`. **Block unintended external requests**. Either inject fully synthetic, timestamp-validated data responses through a tested upstream tool boundary with deny-by-default networking, or report `DATA_ISOLATION_BLOCKED`; don't call an unconstrained upstream graph and label it a valid historical competition.
- The upstream factory supports OpenAI-compatible providers and configurable `llm_provider`, `quick_think_llm`, `deep_think_llm`, endpoint and max-token settings. Verify that provider `ollama` and installed `llama3.2:3b` work through the upstream `langchain` client. Use local loopback only for the first run; **no need to call NVIDIA or OpenAI merely to prove upstream integration**.

### Continuous execution brief for local Codex — do not interrupt for minor approvals

1. Preserve ignored `.env`, `.venv`, `SideDeck-Blueprint/` and saved `results/`. Pull `feat/p2-agent-adapters` safely. Keep secrets private; only count their presence.
2. Create **separate** disposable Python 3.12 environment `.venv-tradingagents/` (ignore it in git if needed); fetch and verify exact upstream SHA, licence and dependencies. Attempt installation with verbose **redacted local** logs, a sensible bounded timeout, and wheel/cache reuse; report whether any constraint actually prevents installation. Do not attempt repeated blind reinstalls. In the separate environment, first verify `import tradingagents` and the exact `TradingAgentsGraph` import, without any model calls.
3. Add tests and implementation for real upstream result `(state, "Buy")`, `(state, "Overweight")`, `(state, "Hold")`, `(state, "Underweight")`, `(state, "Sell")`, `(state, "REVIEW")`, malformed results and missing final state. Keep the five-tier scale distinct from executable orders. If the state itself has an explicitly validated sizing/stop contract, require it; don't assume.
4. Inspect the actual upstream graph's tool/data wiring. Prove that unexpected external vendors/requests cannot be accessed (network allowlist localhost only, not just setting a provider name). Use controlled synthetic AAPL context. Start with minimal supported analysts/rounds and a tight time/token budget; preserve actual upstream multi-agent graph identity. If isolation is not possible without invasive changes, stop *external graph calls only*, implement a fixture-backed graph import/constructor check, mark `DATA_ISOLATION_BLOCKED`, and continue with safe independent tasks.
5. After import and data isolation succeed, make **one** explicit local Ollama graph smoke invocation on `llama3.2:3b`, with controlled output, zero broker tools/orders and bounded runtime. No autonomous scheduled model calls. If the model lacks tool-call/structured-output support required by the pinned graph, report that specific blocker and evaluate the next permitted local model; do not silently switch to paid OpenAI.
6. Persist separate status fields for `UPSTREAM_IMPORT_VERIFIED`, `UPSTREAM_GRAPH_INVOKED`, `UPSTREAM_GRAPH_RUN_VERIFIED`, `DATA_ISOLATION_VERIFIED`, `PROVIDER_INFERENCE_VERIFIED` and `EXECUTABLE_PROPOSAL_VALIDATED`. Provider-only Ollama smoke was already completed: **do not repeat just to show progress**. Include model, upstream SHA, duration, calls/tokens where available, output rating and zero broker/order mutations.
7. Keep CI offline with isolated stubs; run pytest, Ruff, mypy, disposable PostgreSQL; update `TODO.md` and `docs/INTEGRATION_REPORT.md` with exact results. Commit and push normally. If no graph execution is possible, supply a precise blocker, required action, and remaining independent deliverables rather than inventing success.

**Release gate:** Genuine multi-agent TradingAgents graph evidence is distinct from a single-provider LLM reply. A five-tier rating must **not** be treated as an order. No eToro and no unlicensed AI Trading source use.
