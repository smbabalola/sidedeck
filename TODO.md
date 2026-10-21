# SideDeck — Live execution board

> **Governed by [SIDEDECK_STEERING.md](SIDEDECK_STEERING.md)** and `AGENTS.md`. The board below is authoritative for next work; the historical log below is archived context, not current truth. Reconcile with actual branch HEAD and CI at each session.

**Repository/worktree:** `smbabalola/sidedeck`, nested `sidedeck/` checkout, `feat/p5-agent-adapters`. **Safety:** P4 NO-GO; no real-money execution; no provider-paid calls, authenticated broker requests, or demo/paper orders without separate bounded owner approval; four eToro Demo baseline positions protected.

## Current execution board — ordered by priority and dependencies

Each item has **ID | priority | status | dependencies | acceptance | evidence / blocker**. Permitted statuses: READY, IN_PROGRESS, BLOCKED_EXTERNAL, BLOCKED_OWNER, IMPLEMENTED, VERIFIED, CLOSED. The status below describes *next acceptance work* even when portions of the code already exist.

- [x] **SD-001 | P0 | VERIFIED | deps: none | Backtest correctness independent audit.** Next-observation signal timing is explicit, costs reject nonfinite/portfolio-consuming values, trade ledger records signal/execution dates and the returned path is marked independently checked. **Evidence:** `src/sidedeck/application/m2_backtest.py`; `tests/test_m2_backtest_chronology.py`; Batch A CI.
- [x] **SD-002 | P0 | VERIFIED | deps: none | Research spending/identity security hardening.** Provider authorization is a 15-minute, single-run, single-use lease with finite USD/call caps and replay prevention; subprocess allowlisting remains broker-secret free. **Evidence:** `src/sidedeck/application/m2_research_run.py`, `src/sidedeck/application/ai_agents.py`, `tests/test_m2_model_budget_gate.py`, Batch A CI.
- [x] **SD-003 | P0 | VERIFIED | deps: none | Historical-price evidence inventory and offline importers.** Normalized evidence now enforces approved instrument/exchange identity and independently compares common closes without admitting conflicts. eToro entitlement and genuine MSFT history remain NOT_VERIFIED. **Evidence:** `src/sidedeck/application/m2_market_data.py`, `docs/M2_ETORO_MARKET_DATA_ENDPOINT_MATRIX.md`, Batch A CI.
- [ ] **SD-004 | P0 | BLOCKED_EXTERNAL | deps: SD-003 | MSFT genuine valuation admission.** `ALPACA_SIP_ACQUIRED`, `CALENDAR_VERIFIED`, `CORPORATE_ACTIONS_VERIFIED` and `SHARE_BASIS_VERIFIED` milestones: one authorized HTTP 200, 59 MSFT SIP split-adjusted daily bars, 2026-07-29 through 2026-10-20, one-page response, SHA-256 manifest in ignored local data; official Nasdaq 2026 calendar reconciles all 59 sessions and excludes 2026-09-07. Official SEC records match accessions `0001193125-26-323632` (8-K, accepted 2026-07-29 16:04:53 ET) and `0001193125-26-323660` (10-K, accepted 2026-07-29 16:08:01 ET); first eligible close is 2026-07-30. **Accept:** genuine dated evidence with reproducible market-cap/P-E audit, or still NO-GO with precise missing proof. **Blocker:** complete independent 59-row corroboration remains unavailable; Quiver displays a partial public history but its current coverage stops before 2026-10-20 and terms restrict redistribution/product use; Yahoo is rate-limited/unverified. *Do not assert valuation from one source or fixtures*.
- [x] **SD-005 | P1 | VERIFIED | deps: none | MSFT accounting integration and research-input manifest.** Existing MSFT reconstruction remains 2026-06-30 `10/12`, with eight fully reconciled non-valuation periods; new hash-only input manifest preserves cutoff/source lineage and explicitly blocks valuation. **Evidence:** `docs/M2_MSFT_FINANCIAL_RECONSTRUCTION.md`, `src/sidedeck/application/p5_research_manifest.py`, `tests/test_p5_research_manifest.py`.
- [x] **SD-006 | P1 | VERIFIED | deps: SD-001 | Backtest strategy robustness and OOS acceptance.** Added same-observation buy-and-hold benchmark and finite fee/slippage sensitivity grid with locked OOS counts; robustness remains `NOT_ASSESSED` and no fixture profitability claim is emitted. **Evidence:** `src/sidedeck/application/m2_backtest.py`, `tests/test_m2_integrated_batch.py`.
- [x] **SD-007 | P1 | VERIFIED | deps: SD-002, SD-005 | Real dual-agent dry-run acceptance harness.** Offline pair acceptance remains lineage/cutoff/provenance/abstention fail-closed; launcher now records `tradingagents==0.7.0` and the verified `aihf` git identity. No model/provider call was made. **Evidence:** `src/sidedeck/application/p5_agents.py`, `src/sidedeck/application/p5_research_pair_acceptance.py`, `tests/test_p5_agents.py`, `tests/test_p5_research_pair_acceptance.py`.
- [ ] **SD-008 | P1 | BLOCKED_OWNER | deps: SD-004, SD-007 | Bounded MSFT genuine TradingAgents/BuffettAgent research.** **Accept:** approved provider/model, maximum calls and spend enforced, owner-specific consent, genuine result provenance and independent pair acceptance. **Blocker:** owner has not authorized a specific paid provider request; valuation gate fails.
- [x] **SD-009 | P1 | VERIFIED | deps: none | Dashboard research/evidence acceptance.** Sanitized baseline/research endpoints retain expiry, fail-closed, no-order and no-value/credential/broker-ID boundaries; Vite/TypeScript production build passes. **Evidence:** `src/sidedeck/application/p5_demo_dashboard_api.py`, `web/src/App.tsx`, `tests/test_p5_demo_dashboard_api.py`, Batch A CI.
- [x] **SD-010 | P1 | VERIFIED | deps: none | CI and persistence hardening.** CI now runs Alembic head migration and a read-only dashboard build in addition to tests/Ruff/mypy/PostgreSQL service; local SQLite round-trip passes. **Evidence:** `.github/workflows/ci.yml`, Batch A CI.
- [ ] **SD-011 | P1 | BLOCKED_OWNER | deps: SD-001, SD-002, SD-006, SD-008, SD-009, SD-010 | Paper/demo order release and capital assignment.** Separate broker/environment-specific consent, authenticated read-only funds check, protected baseline, risk cap, order/fill/position/exit attribution, idempotency, kill switch. **Accept:** independent audited human approval and controlled scoped release. **Blocker:** no owner order-release authorization. P4 remains NO-GO and eToro original positions untouchable.
- [x] **SD-012 | P2 | VERIFIED | deps: SD-009, SD-010 | Operator runbooks and recovery.** `docs/OPERATOR_RUNBOOK.md` documents loopback startup, verification, disposable migration recovery, backup/restore precautions, outage handling, privacy and release stops. **Evidence:** Batch C docs review and existing replay/migration tests.
- [ ] **SD-013 | P2 | BLOCKED_OWNER | deps: SD-011, SD-012 | Controlled paper soak and formal MVP release.** **Accept:** documented minimum one-month demo observation, metric thresholds, approval record and no serious unresolved incidents. **Blocker:** owner has not released paper execution; no real money.

## Session control and next autonomous batch

**Batch A (verified):** SD-001 + SD-002 + SD-003 + SD-009 + SD-010. Exact-HEAD GitHub CI `39549008720` passed on `367a49bdfb9a7e01bb9ab8963d15d79f133bfb92`. No independent MSFT prices are present in the approved checkout, so SD-004 remains BLOCKED_EXTERNAL.

**Batch B (verified):** SD-005 + SD-006 + SD-007. Exact-HEAD GitHub CI `39549110907` passed on `75eea2e52c013cb7946a80da36c30bf980af67e7`. **Batch C (verified):** SD-012 operator runbooks/recovery. Exact-HEAD GitHub CI `39549183270` passed on `14c846bb2ba24f302f9647a4377645b5480866c7`.

**Batch D (verified partial acquisition; SD-004 remains blocked):** Added explicit Alpaca historical IEX/SIP read-only boundary, independent Nasdaq parser boundary, point-in-time valuation admission, persistent 20-request budget, and completed the one-time authorized MSFT SIP retrieval. No account/trading endpoint, eToro request, paid data or model call was used. No further authenticated request is authorized by this phase. Next unblocked work is offline reconciliation/holiday-calendar handling; full valuation still requires independent evidence and publication-time proof.

### Batch A evidence — 2026-10-21

- Local exact verification before commit: `515 passed, 1 skipped, 3 warnings`; Ruff passed; mypy passed for 104 source files; SQLite Alembic upgrade → downgrade base → upgrade head passed; `web` `npm run build` passed. PostgreSQL service test remains the single skipped local test and is exercised in GitHub CI.
- No authenticated eToro/Alpaca/Saxo request, paid model/data call, broker order, baseline refresh, or credential read was performed. Fixture/offline evidence is not research or trading performance.
- Batch A code commit `367a49bdfb9a7e01bb9ab8963d15d79f133bfb92`; exact-HEAD GitHub CI `39549008720` passed: tests, Ruff, mypy, disposable PostgreSQL and the new Alembic/dashboard-build steps. Genuine MSFT price/valuation evidence remains `BLOCKED_EXTERNAL`; paper release remains `BLOCKED_OWNER`.

### Batch B evidence — 2026-10-21

- Local focused verification: `20 passed`; final full regression `518 passed, 1 skipped, 3 warnings`; Ruff passed; mypy passed for 105 source files. Hash-only MSFT research manifests omit raw content; backtest sensitivity output keeps robustness `NOT_ASSESSED`; paired-agent checks remain offline and proposal-only.
- No provider/model call, SEC download, authenticated broker request, order, baseline refresh or credential read was performed. Batch B is implementation/fixture evidence, not genuine research or performance evidence.

### Batch C evidence — 2026-10-21

- Added `docs/OPERATOR_RUNBOOK.md` covering loopback operation, sanitized recovery, disposable migration rollback, protected baseline handling and privacy/release stops.
- Remaining gates are genuine MSFT price evidence (`BLOCKED_EXTERNAL`), paid-provider/model authorization (`BLOCKED_OWNER`), and all paper/demo execution/release work (`BLOCKED_OWNER` / `NO-GO`).
- Exact-HEAD CI for Batch B and Batch C passed with Python 3.12, disposable PostgreSQL, Ruff, mypy, Alembic upgrade and dashboard build: [39549110907](https://github.com/smbabalola/sidedeck/actions/runs/39549110907), [39549183270](https://github.com/smbabalola/sidedeck/actions/runs/39549183270).

### Batch D evidence — 2026-10-21

- Focused verification: `18 passed`; adapter and valuation modules pass Ruff; mypy passes across 107 source files. `docs/SD004_MARKET_DATA_PLAN.md` records official-source findings and the exact remaining entitlement/provenance blocker.
- Genuine evidence acquired: one bounded authenticated Alpaca SIP market-data read plus public documentation. No SEC download, eToro/Saxo request, paid data, model call, account read or broker action was used. SD-004 remains `BLOCKED_EXTERNAL`.
- Full local regression for Batch D: `532 passed, 1 skipped, 3 warnings`; Ruff passed; mypy passed across 107 source files; Alembic upgrade and dashboard build passed. Exact-HEAD CI `39555238835` passed on `e662e4094d1ad8292cb3f96a499450832a72945a`.
- Authorized retrieval correction: genuine Alpaca SIP evidence was acquired locally under the bounded 20-request approval: 1 HTTP request, status 200, 59 bars, one page, 2026-07-29 to 2026-10-20. Raw bundle and budget remain ignored/local; sanitized manifest only is described above. This does not constitute independent corroboration or valuation acceptance.

**Batch E (verified; SD-004 Phase 3 offline reconciliation) — 2026-10-21**

- Added the official-source 2026 Nasdaq session calendar boundary and tested
  that the 59-bar Jul 29-Oct 20 window is complete after excluding the Sep 7
  Labor Day closure; no interpolation or holiday filling is performed.
- Verified official SEC EDGAR accession/timestamp evidence against the local
  Company Facts lineage: 8-K `0001193125-26-323632` accepted 16:04:53 ET and
  10-K `0001193125-26-323660` accepted 16:08:01 ET on Jul 29. Both reject the
  Jul 29 close; first eligible close is Jul 30. The implementation preserves
  timezone-aware timestamps and applies a strict next-session look-ahead rule.
- Added an offline owner-supplied Yahoo CSV parser that uses historical
  `Close`, never `Adj Close`, and marks provenance/adjustment unverified. The
  public Yahoo history page was rate-limited; no Yahoo rows were acquired.
- SD-004 remains `BLOCKED_EXTERNAL`: no independent price corroboration,
  verified split/dividend basis, or compatible actual-share denominator.
  No new authenticated Alpaca call, account/portfolio/order endpoint, eToro
  request, paid data/model call, or trading action was performed.
- Focused Phase 3 tests: 7 passed. Full local regression: 539 passed, 1
  skipped, 3 warnings; Ruff passed; mypy passed across 110 source files;
  SQLite Alembic upgrade and frontend production build passed. PostgreSQL
  disposable migration/test coverage passed in CI. Exact-HEAD GitHub CI
  `39556465804` passed on `92656da39308fe757244e94f4a1841c5eb4d9049`:
  https://github.com/smbabalola/sidedeck/actions/runs/39556465804. CI emitted
  only Node 20 and ubuntu-latest migration warnings.
- Next safe batch: continue offline R1/R2 evidence and accounting hardening;
  retain SD-004's valuation block until independent price/corporate-action/
  share-basis proof exists. No owner approval is currently required for that
  offline work.

**Batch F (verified; SD-004 Phase 4 corporate actions/share basis) — 2026-10-21**

- Added `p5_msft_corporate_actions.py` and regression tests: no MSFT split
  occurs in the Jul 29-Oct 20 window; latest official split is 2-for-1 on
  2003-02-18; the official $0.91 dividend has 2026-08-20 ex-date. Split-
  adjusted close and dividend-excluded close are kept distinct.
- Added `p5_msft_share_basis.py`: actual common shares outstanding are
  7,425,545,491 measured 2026-07-23; FY26 basic/diluted weighted averages are
  7,429m/7,453m and diluted EPS is $17.95. Valuation admission now explicitly
  rejects a diluted weighted-average denominator as actual shares.
- Investigated Quiver's public historical table as an independent candidate.
  It displays Close separately from Adj. Close, but does not provide complete
  reproducible coverage through Alpaca's 2026-10-20 endpoint in the public
  page, and its terms restrict redistribution/product use. No export or Yahoo
  data was acquired. Independent comparison remains `BLOCKED_EXTERNAL`.
- No authenticated request, paid dataset/model call, credential read,
  account/order endpoint, eToro request, or trading action was performed.
- Focused Phase 4 tests: 11 passed. Full local regression: 544 passed, 1
  skipped, 3 warnings; Ruff passed; mypy passed across 113 source files;
  SQLite Alembic upgrade and frontend production build passed. PostgreSQL
  disposable migration/test coverage passed in CI. Exact-HEAD GitHub CI
  `39572269210` passed on `a50ccda6f3a0a9f8767d7cbeba890fb2afcbe8d8`:
  https://github.com/smbabalola/sidedeck/actions/runs/39572269210. CI emitted
  only Node 20 and ubuntu-latest migration warnings.
- Next action: advance to independent strategy-testing work while retaining
  SD-004's valuation block. Owner action, if MSFT valuation is still desired,
  is to provide a lawful complete independent 59-row export or written data
  license permitting reproducible use; no broker or paid-data authorization is
  being requested.

**Decision record:** MSFT is the first *candidate*, not an approved trade; SOFI is a second sector-specific case. SOFI borrowings-excluding-deposits is supplementary audit only; no generic Buffett D/E approval. No Financial Datasets subscription is required for locally supplied Buffett SEC inputs. Price/valuation remain NO-GO until proved.

**Release gate scoreboard (truthful as-of last confirmed evidence, refresh on run):** G0 engineering previously PASS on `2876fdc` CI; G1 market/valuation BLOCKED; G2 real research NOT_ASSESSED; G3 independent real-data backtest NOT_ASSESSED; G4 paper release NO-GO; G5 operations NOT_ASSESSED. Steering documentation commits after that baseline require fresh CI verification.

**End of each Codex batch:** commit/push, wait for exact-HEAD GitHub CI or record pending, update board statuses and evidence, update next batch plan. Historical records below must never override this board.

---

## Archived M2 chronology (retain for traceability; not the live board)


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
- MSFT SEC reconstruction: latest 2026-06-30 period has `10/12` validated
  metrics; `8` historical periods have all ten non-valuation metrics
  reconciled, while `70` contain at least one validated metric.
  General-sector coverage gate: `FAIL` (`10/12`; valuation has no evidence).
  Outputs are local temporary audit/data artifacts and the raw Company Facts
  file remains ignored; see `docs/M2_MSFT_FINANCIAL_RECONSTRUCTION.md`.
- MSFT valuation: unresolved until historical price adjustment, filing-date
  price and share-basis validation are complete. No market cap or P/E emitted.
- M2 integrated batch: offline market-data normalization, valuation admission,
  dual-agent dry-run planning, research-only backtest analytics and sanitized
  dashboard readiness endpoint implemented; see
  `docs/M2_INTEGRATED_BATCH.md`. Live providers, model calls and broker
  execution remain blocked.
- Integrated batch commits: `fc4b8d5549041b880c64f179a12dc1c551d14788`
  plus drawdown correction `9d6ae298c140cf3129c72aaebef04511bcb9d630`.
- Integrated-batch verification: `485 passed, 1 skipped, 3 warnings`; Ruff
  passed; mypy passed across 103 source files; frontend build passed. GitHub
  runs `39454257672` and `39454308317` were in progress at handoff.
- Local verification: `409 passed, 1 skipped, 3 warnings`; Ruff passed;
  mypy passed across 92 source files; frontend build passed; disposable
  SQLite Alembic upgrade/downgrade passed.
