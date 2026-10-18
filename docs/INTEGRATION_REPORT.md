# Integration-hardening and adapter report

Date: 2026-10-18  
Branch: `feat/p2-agent-adapters`  
Status: offline-safe hardening and code-ready TradingAgents proposal boundary; external model run not verified

## Completed safely

- The demo now executes the exact envelope produced and validated by one worker invocation. A worker that would change its second response cannot bypass validation.
- Each run receives ledger-derived cash and holdings at its decision cutoff; worker output cannot mutate that read-only context.
- Risk uses marked existing positions, projected market exposure, execution spread/fees, cash sufficiency, position caps and stop-risk budget before simulation.
- SQLite journal idempotency plus recovery reconstruction prevents a partially written JSON artifact from reposting economic events.
- Dashboard output includes agent status, final summary, session equity/NAV, positions, exposure, risk decisions and exports. Reset is scoped to `results` or a marker-protected fixture directory.
- Synthetic sessions use weekdays and remain visibly labelled as synthetic, not observed market data.
- Local CSV market import requires a confirmed usage licence, UTC market/ingestion/publication timestamps, approved USD instruments, stale/future checks and weekday observations.
- `TradingAgentsProposalAdapter` is a restricted injected boundary for the pinned `TradingAgentsGraph.propagate(ticker, trade_date)` shape. It normalizes only structured BUY/SELL/HOLD proposals with explicit size, stop and invalidation; broker/credential fields and missing metadata fail closed.

## Verification

- Local: 41 passed, 1 skipped (local PostgreSQL unavailable), 3 existing SQLite datetime-adapter warnings.
- Ruff: passed.
- mypy: passed for 21 source files.
- SQLite Alembic upgrade: passed.
- Disposable PostgreSQL CI: [run 39138613194](https://github.com/smbabalola/sidedeck/actions/runs/39138613194) — Python 3.12, 42 passed, 3 existing SQLite adapter warnings, Ruff and mypy passed for 22 source files. No existing user database was contacted.

## External blockers

- Controlled local smoke evidence: Ollama `llama3.2:3b` returned structured JSON in one synthetic-context request; SideDeck proposal validation accepted the normalized envelope. The evidence is provider-only: upstream import and graph execution were not verified, and no proposal was executed.
- Pinned graph follow-up: the exact upstream graph import succeeded in a disposable Python 3.12 environment after targeted dependency repair. One minimal graph invocation was stopped when its Yahoo `curl_cffi` vendor attempted `fc.yahoo.com`; data isolation is therefore blocked, no graph rating was accepted, and no model/order result is claimed.

- The injected upstream TradingAgents runtime and model/data providers were not installed or executed. The adapter is `CODE_READY`; `UPSTREAM_IMPORT_VERIFIED` and `UPSTREAM_MODEL_RUN_VERIFIED` remain unclaimed pending owner-approved credentials/provider policy.
- `imranpollob/ai-trading` remains licensing-blocked and was not imported, copied, installed or run.
- eToro and all broker access/order paths remain disabled.
