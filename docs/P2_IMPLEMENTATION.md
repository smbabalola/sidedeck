# SideDeck P2 — Proposal-Only AI Agent Integration

**Status:** Approved for scoped development planning. **Do not implement broker execution in P2.**  
**P1 accepted base:** `cae13cfb7f01b8fd3a5c1c2ae21a56ac9de94733`  
**P2 feature branch:** `feat/p2-agent-adapters`  
**Date:** 2026-10-18

## 1. Objective and non-negotiable boundaries

Build a secure, measurable decision gateway between SideDeck and two distinct research/trading frameworks:

- TradingAgents: `TauricResearch/TradingAgents`, pinned upstream reference `e8f5503e9b86d5c2710b0c76b1f686703968c9df` (recheck compatibility; upstream is Apache-2.0).
- AI Trading: `imranpollob/ai-trading`, inspected reference `8f2e287e77851266b0d11ff2ba4a13c15793f79f`. **No licence file was found. Do not vendor, alter, redistribute or execute its source inside this project without first resolving the applicable rights.** Implement only an independently authored protocol adapter/fixture and record the licensing blocker.

The goal is **research proposals, not orders**. P2 must never submit trades to eToro Demo or Real, use broker credentials, mutate a live brokerage account or offer any real-money mode. Keep existing P1 ledger and audit invariants intact.

The experiment retains exactly two separate USD 1,000 logical portfolios: `tradingagents` and `ai-trading`. The four internal investor-style agents in AI Trading are **not** four additional funded competitors; they must eventually coordinate within one `ai-trading` portfolio.

## 2. Architecture

```text
Versioned experiment manifest + deterministic point-in-time market bundle
                  |
          AgentRunCoordinator
             /        \
 TradingAgentsWorker    AITradingProtocolWorker
 (licensed upstream,    (independent stub while
  explicit opt-in)        licence is unresolved)
             \        /
          Untrusted proposal envelopes
                  |
       ProposalSchemaValidator
                  |
    Instrument/Data/Portfolio Policy Gate
                  |
    Immutable run + decision/evidence store
                  |
      Dashboard / inspection / export
              NO BROKER API
              NO ORDER SUBMISSION
```

All research workers are untrusted. They must run out-of-process with least privilege where practical. The parent gateway alone owns IDs, approved instruments, experiment revision, cutoffs, output validation and durable storage. Agent text is never executed as code or interpreted as an order.

## 3. Required application contracts

Prefer extending the existing P1 `TradeIntent` model instead of inventing a parallel inconsistent type.

**AgentRunRequest** (immutable, versioned):
- `run_id`, `experiment_id`, `portfolio_id`, `strategy_id`, `adapter_id`, `adapter_revision`, upstream repository + pinned SHA when applicable.
- `decision_cutoff_utc`, `market_bundle_id`, allowed symbols, non-secret model/provider configuration reference, resource budget, deterministic fixture flag.
- Read-only cash and holdings snapshot (strictly the named portfolio), with valuation-as-of cutoff; no credentials or mutable account tools.

**MarketBundle**:
- Approved, timestamped, provenance-tagged `MarketSnapshot` objects and historical features/news if used, each with observation/publication/ingestion timestamps.
- Data quality and stale-data gates; no future knowledge, inferred timestamps, fabricated prices or random price fallback.
- Identical eligible point-in-time input availability for both competitors; model-specific research methods may differ but must be logged.

**AgentProposalEnvelope**:
- `schema_version`, `run_id`, `portfolio_id`, `adapter_id`, `generated_at`, `data_as_of`, `model/provider/revision`, `upstream_sha`, `decision_inputs_hash`, `prompt_version`.
- Zero or more proposed BUY / SELL `TradeIntent` items, or an explicit HOLD/no-trade result.
- Machine-readable explanation and evidence references (source URLs or local fixture IDs, as-of timestamps), uncertainty, optional thesis and invalidation criteria.
- `estimated_model_cost_usd`, token usage if available, runtime, refusal/failure status, errors.
- Every proposal carries stable strategy/portfolio identity; no free-form execution payload or broker endpoint field.

**ValidationResult**: accepted/rejected state, immutable reason codes, invalid fields and provenance. Fail closed on timeouts, invalid schema, unknown symbol, mismatched portfolio, look-ahead, stale observations, negative/non-finite quantity, oversized result, or missing core evidence. A HOLD result must not be interpreted as an order.

**AgentRunRecord**: append-only run request hash, sanitized agent output, validator result, decision IDs, start/finish/failure times, model costs, code SHA and reproducibility metadata. Retain rejected proposals for audit without leaking credentials or personal data.

## 4. Implementation increments

### P2A — Common gateway, no external agent calls
- Create `src/sidedeck/agents/` with typed interfaces, `AgentRunCoordinator`, independent adapter protocol, conversion to existing `TradeIntent` and validation policies.
- Add deterministic **fixture-only** adapters for both competitors and a common point-in-time fixture bundle.
- Add append-only run/decision storage and migration, if needed; isolate it from P1 accounting journal.
- Add read-only CLI/API for offline fixture runs with report of two competing portfolios. No order filling.
- Add comprehensive negative tests and immutable provenance tests.

**Gate:** both fixture adapters can produce valid or rejected decisions, without touching the ledger or any external service.

### P2B — TradingAgents adapter (isolated opt-in)
- Integrate using official `TradingAgentsGraph.propagate(...)` entrypoint, or supported documented CLI. Inspect the actual upstream pinned version and record API differences.
- Run separately with finite timeout, bounded tokens/cost, memory/CPU limits where available, explicit data-access policy, no executable broker tools.
- Translate its decision/report to a structured proposal; reject ambiguities instead of guessing size.
- No silent latest-price calls that circumvent SideDeck's point-in-time bundle. If upstream cannot enforce the as-of data contract, record the limitation and keep it fixture-only.
- CI must not require a model subscription or external network; explicit owner opt-in only for local smoke tests.

**Gate:** opt-in local TradingAgents worker yields a traceable proposal while the CI suite stays offline and deterministic.

### P2C — AI Trading independent protocol and rights gate
- Implement an **original SideDeck-side** `AITradingAdapterProtocol` and fake worker compatible with the desired proposal shape. The repo's observed MCP execution tools (`buy_shares`, `sell_shares`), simulated $10,000 accounts, crypto agent, timed execution and random-price fallback are **not** safe default interfaces for SideDeck.
- No copying of source, direct imports, vendoring, code modification or runtime installation of `imranpollob/ai-trading` until permissions have been confirmed and recorded in `docs/LICENSING_DECISION.md`.
- When authorised, design a proposal-only external worker with execution tools removed or inaccessible by construction, four research personas feeding one shared portfolio, and strict access to SideDeck-approved data. It must not contact broker endpoints.
- A stub is **not** evidence that the upstream framework has been integrated. Clearly show “blocked — licensing” if unresolved.

**Gate:** protocol/fixture proof is green; actual AI Trading integration remains explicitly pending until rights and safe tool separation are verified.

### P2D — Comparison and evidence
- Report both engines' decisions on the same explicit bundle, identical universe and cutoff, distinguishing fixture runs, real-model analysis and unavailable engine runs.
- Track HOLD/rejected decisions, runtime and model/data costs. No performance/win claims absent orders/fills.
- Record reproducibility details, upstream commit SHAs, versions and as-of lineage.

## 5. Test and security requirements

- CI remains **offline**, credential-free and deterministic. No broker/API calls.
- Tests must prove an agent cannot alter P1 ledger, portfolio balance, positions, order state or another agent's decision history.
- Check spoofed portfolio IDs, unknown/disallowed instruments (including directly constructed ledger events at future execution boundary), currencies, future market/publication/ingestion times, stale EOD/quote data, prompt injection in source text, malformed JSON, non-finite numeric fields, duplicate/contradictory proposals and concurrent run races.
- Test refusal/timeout/process exit/non-zero status/restarts, duplicate `run_id`, cost-budget ceiling, no partial persistence and sanitised logs.
- Verify that adapter test doubles cannot accidentally be mistaken for validated upstream integrations.
- Require explicit strategy-version/prompt-version/model-version/market-bundle-hash provenance.
- Prohibit crypto, crypto ETFs, leverage, shorts, CFDs, FX, unknown symbols and unapproved external data.
- Ensure no arbitrary shell interpolation, no user secret values in logs, no real-money broker credentials or endpoints reachable by these workers.
- Run `pytest`, `ruff check .`, `mypy src`, SQLite migrations, and disposable PostgreSQL CI where schemas change.

## 6. Deliverables and acceptance report

1. Committed adapter contracts and deterministic fixtures for both competitors.
2. Common proposal validator + read-only decision journal and CLI/API.
3. Optional TradingAgents integration evidence, pinned upstream version, smoke-test output and controlled costs.
4. AI Trading licensing decision and honest integration status (blocked if rights unresolved).
5. Failure-mode and isolation test report, full CI URL, branch/SHA, unresolved risks and explicit proof **zero broker order submission paths**.
6. Update `docs/P2_REPORT.md` and relevant ADRs. Report skipped integration tests honestly.

**P2 must not be represented as fully operational with both upstream engines until both real adapters are authorised and independently verified.** Stop for review when P2 gates are reached; do not move to P3 or connect eToro without separate approval.

## 7. Codex instruction

Read `AGENTS.md`, `docs/P1_REPORT.md` and this brief. Start P2A on `feat/p2-agent-adapters`, preserving existing files and untracked local work. First inspect the complete P1 foundation and resolve any conflict with this brief. Implement common proposal contracts, validator, fixture workers, immutable audit/provenance and tests. Do not use eToro, real execution, or run/copy the unlicensed AI Trading code. Stop after P2A for review before connecting actual model runtimes. Commit and push reviewed changes normally, no force push, and report test evidence.
