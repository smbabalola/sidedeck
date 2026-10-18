# SideDeck SD-10C — Native-network data-isolation recovery

**Status:** Approved safe coding work; **no new unrestricted upstream web access authorised**.  
**Base:** `727fd2924c490feace0c76f7ebf1b88ec5395ad7` (2026-10-18), CI [39140134851](https://github.com/smbabalola/sidedeck/actions/runs/39140134851), 50 tests passing.

## What we verified, and what failed

Pinned, licensed `TauricResearch/TradingAgents@e8f5503e9b86d5c2710b0c76b1f686703968c9df` has successfully **imported** in a disposable Python 3.12 environment. Its `TradingAgentsGraph` was **invoked** with a single market analyst and local Ollama, but the run **did not complete**. Before producing a rating, upstream initiated Yahoo `fc.yahoo.com` cookie/crumb traffic via `yfinance` / native `curl_cffi`. A monkeypatch of Python `socket` did not contain that native transport. Mark `UPSTREAM_IMPORT_VERIFIED=true`, `UPSTREAM_GRAPH_INVOKED=true`, `UPSTREAM_GRAPH_RUN_VERIFIED=false`, `DATA_ISOLATION_VERIFIED=false`. Do not conflate with the earlier successful **single-provider Ollama** reply.

### Exact upstream touchpoints (verified against pinned source)

1. `tradingagents/graph/trading_graph.py`: `TradingAgentsGraph.resolve_instrument_context(...)` calls imported `resolve_instrument_identity(ticker)` **before graph execution**; `create_run_state` invokes it. `tradingagents/agents/context.py` resolves the identity through `get_company_profile(ticker)` and Yahoo. For a controlled AAPL fixture, inject an identity fixture before graph construction/calls. Fail closed if a requested ticker has no approved identity.
2. `tradingagents/agents/analysts/market_analyst.py`: `TOOLS=(get_stock_data,get_indicators,get_verified_market_snapshot)`, each from `tradingagents.agents.tools`. Analyst prompts require stock-data and snapshot tools. The tool list is bound during agent/node construction. **Patch/inject before constructing the graph** and verify the **actual ToolNode binds only approved controlled callables**; replacing module names after graph compile is not sufficient.
3. `tradingagents/agents/tools.py` routes functions through `tradingagents.dataflows.router.route_to_vendor`; `tradingagents/dataflows/router.py` defaults to yfinance/other vendors. Memory-log settlement, news/fundamentals, instrument identity and fallback paths may use distinct routes. Cover every reachable branch, not just the three market tools.
4. `TradingAgentsGraph.propagate(...)` returns `(final_state, rating)`, where rating is `Buy / Overweight / Hold / Underweight / Sell / REVIEW`. The SideDeck adapter **already handles this** as a non-executable signal. Do not revisit or synthesize a BUY/SELL order.

## Required recovery path — continuous implementation

### SD-10C-1 — Deterministic fixture-data seam

- Keep upstream source/version unchanged and separately installed. Build a **SideDeck-owned**, versioned research-data capability interface providing a **synthetic AAPL identity, OHLCV window, approved indicator values and verified as-of market snapshot** with explicit fixture timestamps/provenance and the same ticker/cutoff as `MarketBundle`. The identities/quotes must not be represented as genuine market observations.
- Supply controlled tools/identity before constructing upstream `TradingAgentsGraph`, through a tested injection seam or narrowly scoped runtime wrappers **in the separate disposable environment only**. Use fail-closed errors on unexpected tool names, sources, ticker, dates, public URL or unverified news/memory path; no live Yahoo, SEC, FRED, news, Polymarket, credential-bearing tools.
- Carefully inspect the actual compiled graph's analyst tool bindings and instrument context. Include memory/reflection and identity paths; do not assume selecting only the market analyst disables all other network-capable graph steps.
- Do not monkeypatch away evidence of missed network calls and then claim the network is isolated. Tool routing controls **data correctness**; they do not by themselves secure native HTTP libraries.

### SD-10C-2 — Native-transport network boundary

- **An operating-system-level default-deny network boundary is mandatory before any genuine graph call**. Neither Python `socket` nor `requests` monkeypatching proves `curl_cffi` cannot connect. The guard must cover native code, subprocesses and DNS and be validated by a harmless negative `curl_cffi` / Yahoo connection attempt that is **blocked before egress**, without permitting contact to the remote host.
- Choose a mechanism available without destructive changes to the user's Windows environment: e.g. a disposable isolated Linux container/WSL namespace with outbound networking disabled, or a verified per-process OS firewall/sandbox; do **not** assume Docker or WSL works. Do not change broad Windows firewall policy, install privileged networking software, or alter user's existing services without approval.
- To permit actual **Ollama on localhost** while isolating the agent, use a specific non-HTTP trusted host-side mediation mechanism (e.g. an allowlisted model-only IPC relay) or an OS-enforced allowlist allowing only the exact loopback Ollama endpoint. For a networkless namespace, host `127.0.0.1` is **not automatically reachable** from inside the namespace. Do not re-enable arbitrary egress merely to make Ollama work.
- Verify requests to `fc.yahoo.com`, `query*.finance.yahoo.com` and an arbitrary test domain are denied at the native transport, including DNS, while the controlled Ollama path works. Log **only destinations/reason/status**, never credentials or raw prompts. If OS isolation is unavailable, finish the fixture tools, run a **fully offline stub-model graph**, mark `OS_EGRESS_BOUNDARY_BLOCKED`, and **do not** attempt another actual networked graph run.

### SD-10C-3 — One true graph smoke test, only after both gates pass

- Use exact upstream SHA and disposable Python 3.12 environment; one AAPL-only market-analyst graph invocation with a small supported round/token budget, bounded wall-clock time and local Ollama `llama3.2:3b` if compatible. Use no paid OpenAI/NVIDIA calls.
- Capture distinct booleans and evidence: `UPSTREAM_IMPORT_VERIFIED`, `GRAPH_INVOKED`, `GRAPH_COMPLETED`, `MODEL_CALLED_THROUGH_GRAPH`, `DATA_FIXTURE_ISOLATION_VERIFIED`, `NATIVE_EGRESS_DENIED`, `BROKER_CALLS=0`, `ORDER_MUTATIONS=0`. `GRAPH_COMPLETED` requires evidence of actual finished multi-agent workflow and a final rating or explicit `REVIEW`; a provider-only response or mocked graph does not count.
- Feed the **rating signal only** through SideDeck's existing proposal validator, audit and optional risk preflight; no invented quantity/stop/invalidation and **no** ledger or broker mutation. If graph fails due to local model tool use, report that separately (`MODEL_TOOL_CAPABILITY_BLOCKED`); do not misattribute it to market data.
- Write redacted status/evidence under ignored `results/`. Add a clear, explicit opt-in local CLI for graph smoke; offline CI must have no real network dependencies.

### SD-10C-4 — Test and document once, then continue

- Unit tests must show: identity cannot fall back to live Yahoo; actual compiled tool nodes cannot contain remote vendor tools; unknown tool/name/date fails closed; synthetic as-of provenance is intact; native transport isolation gate is mandatory; model and tool failures are distinct from broker mutations.
- Run full `pytest`, Ruff, mypy and disposable PostgreSQL CI; preserve `SideDeck-Blueprint/`, `.env`, `.venv` and local results. Update `TODO.md`, `docs/REAL_AGENT_SMOKE_TEST.md` and `docs/INTEGRATION_REPORT.md` in the same feature commits. Normal push only. Draft PR #1 must remain unmerged.
- **Do not stop for incremental signoffs** while doing safe source/fixture/test work. Stop only an actual external/privileged network change, secret/paid-provider request, or broker change. If network sandbox is unavailable, report exactly what's missing and proceed with a provider-free graph using deterministic LLM fixtures.

## Codex command — copy once

Synchronise `feat/p2-agent-adapters`, preserving ignored/untracked files. Read `TODO.md`, `AGENTS.md` and `docs/DATA_ISOLATION_RECOVERY.md`. Execute SD-10C-1 through SD-10C-4 continuously. First replace upstream identity/data-tool paths with verified synthetic fixtures at graph construction, then independently prove native `curl_cffi` egress is blocked by an OS-level sandbox without changing existing Windows firewall/service settings. Run one real Ollama graph only if both gates pass. If not, do safe offline compiled-graph validation and report the exact blocker. Do not allow Yahoo/other vendor calls, use OpenAI/NVIDIA, submit orders, access eToro, or copy unlicensed AI Trading code. Test, document, update TODO, commit and push normally, then report evidence.
