# Integration-hardening and adapter report

Date: 2026-10-18  
Branch: `feat/p2-agent-adapters`  
Status: offline-safe synthetic-data hardening and code-ready TradingAgents proposal boundary; external model run not verified

## Completed safely

- The demo now executes the exact envelope produced and validated by one worker invocation. A worker that would change its second response cannot bypass validation.
- Each run receives ledger-derived cash and holdings at its decision cutoff; worker output cannot mutate that read-only context.
- Risk uses marked existing positions, projected market exposure, execution spread/fees, cash sufficiency, position caps and stop-risk budget before simulation.
- SQLite journal idempotency plus recovery reconstruction prevents a partially written JSON artifact from reposting economic events.
- Dashboard output includes agent status, final summary, session equity/NAV, positions, exposure, risk decisions and exports. Reset is scoped to `results` or a marker-protected fixture directory.
- Synthetic sessions use weekdays and remain visibly labelled as synthetic, not observed market data.
- Local CSV market import requires a confirmed usage licence, UTC market/ingestion/publication timestamps, approved USD instruments, stale/future checks and weekday observations.
- `TradingAgentsProposalAdapter` is a restricted injected boundary for the pinned `TradingAgentsGraph.propagate(ticker, trade_date)` shape. It normalizes only structured BUY/SELL/HOLD proposals with explicit size, stop and invalidation; broker/credential fields and missing metadata fail closed.
- `SyntheticResearchBoundary` is a SideDeck-owned, deterministic AAPL-only tool seam with fixed USD point-in-time provenance. Its identity, OHLCV, indicator and verified-snapshot calls reject unknown tools, vendors, tickers and dates rather than falling back to Yahoo. `OfflineTradingAgentsGraph` validates the complete sequence with a deterministic `Hold` stub.

## Verification

- Local: 49 passed, 1 skipped (local PostgreSQL unavailable), 3 existing SQLite datetime-adapter warnings.
- Ruff: passed.
- mypy: passed for 21 source files.
- SQLite Alembic upgrade: passed.
- Disposable PostgreSQL CI: [run 39140051347](https://github.com/smbabalola/sidedeck/actions/runs/39140051347) — Python 3.12, 50 passed, 3 existing SQLite adapter warnings, Ruff and mypy passed for 22 source files. No existing user database was contacted.

## External blockers

- Controlled local smoke evidence: Ollama `llama3.2:3b` returned structured JSON in one synthetic-context request; SideDeck proposal validation accepted the normalized envelope. The evidence is provider-only: upstream import and graph execution were not verified, and no proposal was executed.
- Pinned graph follow-up: the exact upstream graph import succeeded in a disposable Python 3.12 environment after targeted dependency repair. One minimal graph invocation was stopped when its Yahoo `curl_cffi` vendor attempted `fc.yahoo.com`; data isolation is therefore blocked, no graph rating was accepted, and no model/order result is claimed.

- The licensed pinned TradingAgents runtime **was installed sufficiently for the exact graph import to succeed** in a disposable Python 3.12 environment. `UPSTREAM_IMPORT_VERIFIED=true`. A graph invocation began but was stopped by an upstream Yahoo `curl_cffi` network attempt, so `UPSTREAM_GRAPH_RUN_VERIFIED=false` and `DATA_ISOLATION_VERIFIED=false`. The prior single Ollama model-only test is separate evidence. See `docs/DATA_ISOLATION_RECOVERY.md` for controlled tool injection and OS-enforced native egress boundaries.
- SD-10C native isolation remains blocked: Docker's Linux daemon was unavailable and WSL was not an already-provisioned default-deny namespace with an allowlisted Ollama mediation. No Windows firewall/service changes were made, no native `curl_cffi` remote request was repeated, and no real graph was attempted after the failed gate. This is recorded as `OS_EGRESS_BOUNDARY_BLOCKED`, not as evidence that Python-level guards contain native transport.

## SD-10C verification

- Commit: `8c4566d24d00a7045701202d22703a7f5a3171ae`.
- Local: 59 passed, 1 skipped (existing local PostgreSQL availability skip), 3 known SQLite datetime-adapter warnings; Ruff passed; mypy passed for 23 source files; SQLite Alembic upgrade passed.
- CI: [GitHub Actions run 39140855365](https://github.com/smbabalola/sidedeck/actions/runs/39140855365) passed on Python 3.12 with pytest, Ruff and mypy; disposable PostgreSQL container initialization passed. No existing user database was contacted.
- Offline graph: deterministic `Hold`, repeated replay equality, fixture provenance intact, zero model/broker/order/ledger mutations.
- `imranpollob/ai-trading` remains licensing-blocked and was not imported, copied, installed or run.
- eToro and all broker access/order paths remain disabled.
## SD-11A eToro historical-data preparation

- `sidedeck.domain.etoro.EtoroHistoricalDataClient` is a typed, read-only, transport-injected boundary. It has no order imports or methods, accepts only the fixed official eToro API host, resolves only SideDeck's approved AAPL/MSFT/SPY/QQQ instruments, rejects leveraged/CFD-like or non-USD variants, clamps daily requests to 1,000 candles, retries only bounded HTTP 429 responses, and never falls back to Yahoo.
- Candle validation rejects malformed timestamps, future or incomplete sessions, duplicate timestamps, bad volume and invalid OHLC relationships. `CoverageReport` returns `PASS_5Y_DAILY`, `INSUFFICIENT_DEPTH` or `UNVERIFIED`; it does not fill gaps or turn weekly data into daily history.
- `sidedeck.data_probe` is prepared but inert without `--market-data-only --allow-read-network --confirm-owner-read-only` and both environment variables. No eToro credential was read and no eToro request was made in this sprint.
- Official documentation reviewed: [Market Data & Real-Time](https://builders.etoro.com/products/market-data-realtime), [API FAQ](https://builders.etoro.com/faq), [API Quick Reference](https://builders.etoro.com/reference), [authentication and API keys](https://builders.etoro.com/learn/authentication-and-api-keys), and [rate-limit guidance](https://builders.etoro.com/learn/rate-limits-and-429-handling). These establish the market-data surface and credential/rate-limit requirements, but not this account's earliest date, daily depth, adjustment policy or storage rights.
- Coverage verdict: **UNVERIFIED** pending explicit read-only owner approval. The existing licensed local CSV import is the prepared fallback; no automatic Yahoo fallback exists.
