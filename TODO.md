# SideDeck M2 living TODO

## Dual-agent runtime verification — 2026-10-20

- [x] Verify isolated TradingAgents and AI Hedge Fund package imports and
  inspect their research-only interfaces without executing either runtime.
- [x] Add rich, provenance-aware dual-agent research evidence validation with
  cutoff parity, model lineage, abstention and unavailable-data fail-closed
  behavior.
- [x] Preserve broker-secret filtering, proposal-only decisions and disabled
  execution boundaries.
- [x] Resolve AI Hedge Fund upstream identity: distribution `aihf`, pinned as
  `aihf==2.5.0+git.ec025370c66cf71d3ea2f2d8f463b5934c1c48af` (clean editable
  checkout; dirty or unrevisioned installs fail closed).
- [x] Verify BuffettAgent data interface from source: daily runs read only
  `get_financial_metrics(ttm)` + optional `get_company_facts`; Financial
  Datasets is not required with `--fundamentals-json` (preflight updated).
- [x] Add no-network SOFI coverage/cost report
  (`p5_buffett_coverage`): ROE 20/20, EPS 5/20 (not newest), other 10 fields
  0/20; coverage gate FAIL; prompt ~905 input tokens, one call, Anthropic
  output cap 4096. See `docs/M2_BUFFETT_DATA_COMPATIBILITY.md`.
- [x] Bank-aware SEC reconstruction (`p5_sec_bank_metrics`): net margin
  17/20 and revenue growth 14/20 included after reconciliation against
  independent 3-month facts; 2021-Q1 2022 excluded (SPAC predecessor
  discontinuity); D/E `borrowings_excluding_deposits` calculated but excluded
  pending owner approval; FCF NOT_MEANINGFUL (loan originations in OCF); BVPS
  refused; gross/operating margin and current ratio NOT_APPLICABLE.
- [x] Bank coverage profile: SOFI moat FULL; management, financial strength,
  valuation NO_EVIDENCE; relevant fields 3/7; gate FAIL. Prompt ~931 tokens.
- [x] Market-cap candidate audit (`p5_market_cap_evidence`): 11 candidates
  (cover shares × first close after filing), unvalidated, audit only; no
  numeric P/E. See `docs/M2_SOFI_BANK_METRICS.md`.
- [ ] Owner decisions: D/E definition; management EPS basis; consolidated
  price corroboration; first acceptance instrument (recommend a non-financial
  company first, SOFI second).
- [ ] BLOCKED (owner): PostgreSQL disposable test environment; independent of
  offline research work.
- [ ] Obtain explicit owner authorization for a bounded real SOFI research run
  and permitted model/data provider access.
- [ ] Execute genuine TradingAgents and BuffettAgent research only after that
  authorization; no results are accepted from this batch as real research.

## Verification

- Branch: `feat/p5-agent-adapters`
- Latest local commit: `d9a78fb561ee6b428bf4fe5641fa6b5dea68a834` (pushed to
  `origin/feat/p5-agent-adapters`).
- CI baseline: GitHub Actions run `39421932813` passed before this offline
  verification batch; no live-research workflow was triggered.
- TradingAgents: import/signature verified; graph execution not attempted.
- AI Hedge Fund: Buffett v2 import/signature verified; identity
  `aihf==2.5.0+git.ec02537…`; Financial Datasets not needed with local SEC
  input; execution blocked by SEC coverage and owner authorization; no call
  attempted.
- Version/data-compatibility batch (2026-10-20): `430 passed, 1 skipped,
  3 warnings`; Ruff passed; mypy passed across 94 source files; Alembic at
  `0005_etoro_demo_books` (no schema change). Commit `1380794`; CI run
  `39438231148` passed
  (https://github.com/smbabalola/sidedeck/actions/runs/39438231148).
- Bank metrics / valuation evidence batch (2026-10-20): `455 passed,
  1 skipped, 3 warnings`; Ruff passed; mypy passed across 96 source files;
  Alembic at head (no schema change). Commit `458a76a`; CI run
  `39443511576` passed
  (https://github.com/smbabalola/sidedeck/actions/runs/39443511576).
- Broker execution: disabled; eToro/Saxo/Alpaca untouched.
- P4: `P4_DECISION=NO-GO`.
- Local verification: `409 passed, 1 skipped, 3 warnings`; Ruff passed;
  mypy passed across 92 source files; frontend build passed; disposable
  SQLite Alembic upgrade/downgrade passed.
