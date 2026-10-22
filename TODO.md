# SideDeck — Live execution board

> **Governed by [SIDEDECK_STEERING.md](SIDEDECK_STEERING.md)** and `AGENTS.md`. The board below is authoritative for next work; the historical log below is archived context, not current truth. Reconcile with actual branch HEAD and CI at each session.

**Repository/worktree:** `smbabalola/sidedeck`, nested `sidedeck/` checkout, `feat/p5-agent-adapters`. **Safety:** P4 NO-GO; no real-money execution; no provider-paid calls, authenticated broker requests, or demo/paper orders without separate bounded owner approval; four eToro Demo baseline positions protected. **Broker priority (2026-10-21, [ADR-003](docs/ADR-003-etoro-demo-primary-broker.md)):** eToro Demo PRIMARY, Alpaca PAPER SECONDARY, eToro Real permanently excluded. Execution release `NO_GO`, broker execution `DISABLED`.

## Current execution board — ordered by priority and dependencies

### Milestone 0 — first eToro Demo MSFT trade (steering §10; highest priority)

- [x] **SD-055 | P0 | VERIFIED | deps: SD-053 | Pilot intent and owner-signature verification.** Owner signed 2026-10-22; SideDeck verifier `signature_valid: true` and independent `ssh-keygen -Y verify` Good (owner@sidedeck, ED25519 SHA256:7qb8dAz9…/rUI, namespace `sidedeck-etoro-pilot-release`); SHA-256(canonical) = pinned digest `71e111b3…9a62`; signer key pinned; release not consumed.
- [x] **SD-056 | P0 | VERIFIED | deps: SD-054 | Final broker execution transport review.** Independent read-only security review of the full order path: **0 critical, 0 high**. Fixed with tests: (M1) any interruption after the open write trips the kill-switch and writes an UNRESOLVED 'position may be OPEN' report; (M2) the production factory validates lock + credentials before the single-use release is consumed; (M3) open refused with < 20 min of window left, close TTL clipped to window end; (M4) SD-041 guard also catches `from … import` and string references, constructor lock test is `is True`; (M5) dedicated `sidedeck-etoro-pilot-approval` namespace and a signing command that re-checks the digest file against the on-screen digest; lows: lost open acknowledgement → UNRESOLVED immediately, stray pending orders block COMPLETE, stale approval signatures removed, signer key pinned by SHA-256. Accepted lows: transport close URL bound by the desk (not the transport); derived P&L caveated; stale recorded baseline gate superseded by the live preflight reconcile.
- [ ] **SD-057 | P0 | BLOCKED_OWNER | deps: SD-055, SD-056 | Preflight and release readiness.** All offline prerequisites pass; release-bound unlock implemented (`UNLOCKED_PILOT_DIGEST`, default None; only the signed digest can open a transport; suite passes with it simulated and sockets blocked). **Blocker:** owner's explicit final release per `docs/SD057_FIRST_DEMO_TRADE_RELEASE_REQUEST.md`.
- [ ] **SD-058 | P0 | BLOCKED_OWNER / HOST_SECURITY_APPROVAL_REQUIRED | deps: SD-057 | First Demo opening order.** Owner released SD-057 (2026-10-22). The one-line digest-specific unlock (`UNLOCKED_PILOT_DIGEST = "71e111b3…9a62"`; global lock stays False) is implemented in the working tree and passes the full offline suite (sockets blocked), Ruff and mypy, but is **uncommitted**: Claude Code auto mode denied the commit/push as security-weakening. Supported path: the owner switches Claude Code out of auto mode (Shift+Tab to the default ask mode) so the exact commit/push appears as an interactive Allow/Deny prompt; otherwise the network stays locked. GitHub HEAD remains locked. Window Fri 2026-10-23 14:00–15:30 UTC (open by 15:10 UTC); never rolled forward.
- [ ] **SD-059 | P0 | IMPLEMENTED | deps: SD-058 | Acknowledgement and fill reconciliation.** Lookup-only recovery (≤ 3), referenceId→orderId→positionId lineage, unknown/lost acknowledgement → UNRESOLVED + kill-switch, never resubmitted; terminal partial IOC fill closes exactly the filled units (tested).
- [ ] **SD-060 | P0 | BLOCKED_OWNER | deps: SD-059 | Separate close authorization.** Runtime owner signature over the exact full-close request (30 min TTL); declining keeps the position OPEN and trips the kill-switch (tested).
- [ ] **SD-061 | P0 | IMPLEMENTED | deps: SD-060 | Closing order and final reconciliation.** COMPLETE only when close FILLED + final reconcile MATCHED + zero SideDeck positions; pending/partial close → UNRESOLVED (tested).
- [ ] **SD-062 | P0 | IMPLEMENTED | deps: SD-061 | Independent trade accounting and audit.** Entry (units, avg price, fees, notional, limit, fresh ask, slippage) BROKER_REPORTED from orders:lookup; realized P&L DERIVED from cash-credit change (close price not in documented close-info). Post-trade: independent audit against the eToro Demo UI history.
- [ ] **SD-063 | P1 | READY | deps: SD-061 | Transition to strategy-driven autonomous Demo trading.** Design and test offline a bounded autonomous Demo policy (strategy admission, signal qualification, deterministic risk/capital/drawdown limits, durable expiry, recovery, alerts, audit) — separately reviewed and owner-released before any use.
- [ ] **SD-064 | P1 | IMPLEMENTED | deps: SD-058 | Owner-signed network unlock grants (replace the source-constant unlock).** `sd064_unlock_grant`: canonical grant (schema `sidedeck-unlock-grant/1`) signed by the owner in namespace `sidedeck-network-unlock-grant`; Demo only (Real refused); kinds `pilot_release` (≤ 8 h, ≤ 12 requests / 2 writes) and `autonomous_policy` (≤ 7 days, bounded caps); one subject digest; `issued_by` must be the owner principal; pinned signer key; fail-closed expiry at every check; permanent revocation; hash-chained audit ledger (edits detected; tail truncation needs an external anchor — open). 25 tests with real ssh-keygen signatures. **Not yet wired** into the order transport: deliberately deferred until after the SD-058 pilot and re-lock so the reviewed pilot path is unchanged before the window. **Next:** after re-lock, replace `UNLOCKED_PILOT_DIGEST` with an `UnlockAuthority` check (independent review), add a grant-signing CLI and an external ledger anchor.

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
- [ ] **SD-011 | P1 | BLOCKED_OWNER | deps: SD-001, SD-002, SD-006, SD-008, SD-009, SD-010 | Paper/demo order release and capital assignment.** Separate broker/environment-specific consent, authenticated read-only funds check, protected baseline, risk cap, order/fill/position/exit attribution, idempotency, kill switch. **Accept:** independent audited human approval and controlled scoped release. **Blocker:** no owner order-release authorization. P4 remains NO-GO and eToro original positions untouchable. **2026-10-21:** target broker is now eToro Demo (SD-036 offline desk); release additionally requires SD-037, SD-038 and residual risks R2–R6 in `docs/SD036_ETORO_DEMO_CONTRACT_REVIEW.md` resolved.
- [x] **SD-012 | P2 | VERIFIED | deps: SD-009, SD-010 | Operator runbooks and recovery.** `docs/OPERATOR_RUNBOOK.md` documents loopback startup, verification, disposable migration recovery, backup/restore precautions, outage handling, privacy and release stops. **Evidence:** Batch C docs review and existing replay/migration tests.
- [ ] **SD-013 | P2 | BLOCKED_OWNER | deps: SD-011, SD-012 | Controlled paper soak and formal MVP release.** **Accept:** documented minimum one-month demo observation, metric thresholds, approval record and no serious unresolved incidents. **Blocker:** owner has not released paper execution; no real money.
- [x] **SD-014 | P1 | VERIFIED | deps: SD-001, SD-003 | Deterministic strategy catalogue.** Four versioned proposal-only strategies expose parameter, holding-period and next-observation execution contracts. **Evidence:** `src/sidedeck/application/sd014_strategy_engine.py`; `tests/test_sd014_strategy_engine.py`; Batch G CI.
- [x] **SD-015 | P1 | VERIFIED | deps: SD-003, SD-004 | Genuine historical-data boundary.** Reusable normalized-bar conversion preserves caller provenance; the 59-session MSFT SIP bundle is classified `INSUFFICIENT_DATA`, not profitability evidence. **Evidence:** `docs/SD014_STRATEGY_VALIDATION.md`; local ignored SIP manifest; Batch G CI.
- [x] **SD-016 | P1 | VERIFIED | deps: SD-014, SD-015 | Chronological robustness machinery.** Parameter surfaces, in-sample-only selection, locked OOS boundary, embargo configuration, walk-forward windows and fee/slippage controls are deterministic and tested. **Evidence:** `sd014_strategy_engine.py`; `test_sd014_strategy_engine.py`; Batch G CI.
- [x] **SD-017 | P1 | VERIFIED | deps: SD-016 | Proposal portfolio simulation.** Equal weights, exposure/correlation controls, attribution and configurable drawdown kill-switch simulation are implemented without order or broker paths. **Evidence:** `sd014_strategy_engine.py`; `test_sd014_strategy_engine.py`; Batch G CI.
- [x] **SD-018 | P1 | VERIFIED | deps: SD-016, SD-017 | Acceptance framework.** Reports annualized return, drawdown, profit factor, Sharpe, win rate, exposure, OOS counts and explicit acceptance status; minimum-data gates remain fail-closed. **Evidence:** `sd014_strategy_engine.py`; `docs/SD014_STRATEGY_VALIDATION.md`; Batch G CI.
- [x] **SD-019 | P2 | VERIFIED | deps: SD-014, SD-018 | Dashboard catalogue surface.** Read-only strategy metadata and acceptance status are exposed through a sanitized loopback endpoint and React view; no simulated broker holdings are implied. **Evidence:** `p5_demo_dashboard_api.py`, `web/src/App.tsx`, dashboard tests; Batch G CI.
- [x] **SD-020 | P1 | VERIFIED | deps: SD-015, SD-018 | Five-year data inventory and bounded retrieval plan.** Read-only inventory found no SPY/QQQ history and no five-year MSFT series; it documented the existing 59-bar MSFT SIP and unrelated 701-bar SOFI IEX bundles without reading credentials or contacting providers. **Evidence:** `docs/SD020_FIVE_YEAR_DATA_PLAN.md`; local ignored-file inventory.
- [x] **SD-021 | P1 | VERIFIED | deps: SD-020 | Approved five-year SPY/QQQ/MSFT SIP retrieval and proposal-only validation.** Exact owner-authorized scope completed: 1,254 bars per ticker, 1 request per ticker, 3/60 global requests, offline admission, deterministic strategy evaluation and sanitized research reports. **Limit:** `ADMITTED_RESEARCH_ONLY`; independent corporate-action/dividend corroboration remains pending and SD-004 stays blocked. **Evidence:** `docs/SD021_RESULTS.md`, `src/sidedeck/application/p5_sd021_validation.py`, `src/sidedeck/application/p5_sd021_research.py`, ignored local manifests/bundles.
- [x] **SD-022 | P1 | VERIFIED | deps: SD-021 | Independent strategy robustness audit.** Recalculated metrics independently, changed the denominator to completed BUY→SELL trades, verified locked OOS/selection boundaries and portfolio weights/correlations, and reclassified the five prior screens to two robustness survivors, one OOS rejection and nine insufficient-data outcomes. **Evidence:** `docs/SD022_ROBUSTNESS_AUDIT.md`; `src/sidedeck/application/sd022_robustness_audit.py`; `tests/test_sd022_robustness_audit.py`.
- [x] **SD-023 | P1 | VERIFIED | deps: SD-022 | Independent corporate-action and benchmark evidence.** Independently recomputed price-only benchmarks from all three saved five-year bundles, reconciled ending equity to the research reports, verified the existing limited MSFT split/dividend record, and kept SPY/QQQ ETF actions and total-return figures `NOT_ASSESSED`/`UNAVAILABLE`. No authenticated requests; SD-004 remains blocked. **Evidence:** `docs/SD023_CORPORATE_ACTION_BENCHMARK_AUDIT.md`; `src/sidedeck/application/sd023_corporate_action_audit.py`; `tests/test_sd023_corporate_action_audit.py`.
- [x] **SD-024 | P1 | VERIFIED | deps: SD-023 | ETF distribution and benchmark evidence boundary.** Added a fail-closed owner-supplied/public evidence parser with split/distribution semantics, ex-date/payment-date validation, source-class rejection and explicit price-only versus total-return labels. No ETF records were available, so SPY/QQQ remain `NOT_ASSESSED`. **Evidence:** `docs/SD024_ETF_DISTRIBUTION_EVIDENCE.md`; `src/sidedeck/application/sd024_etf_distribution_evidence.py`; `tests/test_sd024_etf_distribution_evidence.py`.
- [x] **SD-025 | P1 | VERIFIED | deps: SD-024 | Benchmark/report integration.** Strategy validation summaries and the loopback API now expose sanitized price-only benchmark convention, metrics, corporate-action status and explicit total-return availability from local SD-023 audits; malformed/missing audits fail closed and `UNAVAILABLE` total return is preserved. **Evidence:** `docs/SD025_BENCHMARK_REPORT_INTEGRATION.md`; `src/sidedeck/application/p5_demo_dashboard_api.py`; `tests/test_p5_demo_dashboard_api.py`.
- [x] **SD-026 | P1 | VERIFIED | deps: SD-025 | Dashboard benchmark presentation.** Added a read-only dashboard view for benchmark convention and evidence status with explicit price-only/total-return wording and no performance recommendation language; frontend production build passes. **Evidence:** `web/src/App.tsx`; `docs/SD025_BENCHMARK_REPORT_INTEGRATION.md`; Batch M.


- [x] **SD-027 | P0 | VERIFIED | deps: SD-017, SD-022, SD-026 | Offline Alpaca paper execution safety readiness.** Independently reproduced a `NO_GO` matrix covering broker isolation, disabled order submission, proposal boundary, idempotency, stale quotes, duplicate orders, partial fills, reconciliation, approval signatures, kill-switch and account separation. Residual release issues are explicit; no broker request/order/owner self-approval occurred. **Evidence:** `docs/SD027_PAPER_READINESS_AUDIT.md`; `src/sidedeck/application/sd027_paper_readiness_audit.py`; `tests/test_sd027_sd028_audits.py`.
- [x] **SD-028 | P1 | VERIFIED | deps: SD-017, SD-022 | SPY/QQQ joint portfolio economics and risk audit.** Deterministically aligned 1,254 sessions, computed equal-weight ledger, price-only benchmark, correlation, exposure, concentration and drawdown; turnover/cost/regime sensitivity remain explicitly unassessed. No trading approval inferred. **Evidence:** `docs/SD028_PORTFOLIO_ECONOMICS.md`; `src/sidedeck/application/sd028_portfolio_economics.py`; `tests/test_sd027_sd028_audits.py`.
- [x] **SD-029 | P1 | VERIFIED | deps: SD-027 | Dry-run operator rehearsal and release evidence pack.** Completed isolated in-memory intent → external human-approval record → simulated submission/ack/fill/exit lineage, partial fills, idempotency conflict, rollback and emergency stop tests. No broker state, HTTP calls or order actions; `broker_execution=DISABLED`. SD-011/013 remain blocked. **Evidence:** `docs/SD029_PAPER_RELEASE_CHECKLIST.md`; `src/sidedeck/application/sd029_operator_rehearsal.py`; `tests/test_sd029_operator_rehearsal.py`.
- [x] **SD-030 | P1 | VERIFIED | deps: SD-029 | Release-gate evidence pack hardening.** Added a sanitized machine-readable report combining SD-027 `NO_GO` controls and SD-029 rehearsal results; it requires separate owner approval, preserves protected-baseline status, and rejects any attempt to emit credentials/account IDs/order controls or a paper-release `GO`. **Evidence:** `docs/SD030_RELEASE_GATE_REPORT.md`; `src/sidedeck/application/sd030_release_gate_report.py`; `tests/test_sd030_release_gate_report.py`.
- [x] **SD-031 | P1 | VERIFIED | deps: SD-030 | Operator evidence surface.** Exposed the sanitized release-gate report through the read-only local dashboard/API with fail-closed loading/error states, regression coverage and an explicit `NO_GO`/`DISABLED` dashboard panel. **Evidence:** `src/sidedeck/application/p5_demo_dashboard_api.py`; `web/src/App.tsx`; `tests/test_p5_demo_dashboard_api.py`; `docs/SD031_OPERATOR_EVIDENCE_SURFACE.md`.


- [x] **SD-032 | P0 | VERIFIED | deps: SD-027, SD-029, SD-030 | Durable offline paper intent and idempotent dispatcher boundary.** Added a SQLite-backed append-only intent/event store with tenant/broker/environment/account-scope identity, conflicting client-order rejection, atomic idempotency, partial/full simulated-fill replay and restart recovery. State transitions fail closed and the only acknowledgement is `offline-simulated`; no broker client or authenticated call exists. **Evidence:** `docs/SD032_DURABLE_PAPER_INTENT.md`; `src/sidedeck/application/sd032_durable_paper_intent.py`; `tests/test_sd032_durable_paper_intent.py`.
- [x] **SD-033 | P0 | VERIFIED | deps: SD-032 | Independent signed approval and emergency-stop enforcement.** Added a verifier-only approval store using an externally supplied public-key/verifier boundary, scoped intent digest, expiry, requester/approver separation and replay prevention. Kill-switch state persists across restart and requires separate operator clearance; signing secrets are never generated or stored. **Evidence:** `docs/SD033_APPROVAL_KILLSWITCH.md`; `src/sidedeck/application/sd033_approval_killswitch.py`; `tests/test_sd033_approval_killswitch.py`.
- [x] **SD-034 | P1 | VERIFIED | deps: SD-032, SD-033 | Offline broker-reconciliation contract and bounded owner-read proposal.** Added mock-only acknowledgement, partial/full fill, exit attribution and duplicate/missing/out-of-order/invalid-event detection, plus a dormant three-request Alpaca PAPER read-only proposal. No authenticated read was executed; release remains `NO_GO` and transport `DISABLED`. **Evidence:** `docs/SD034_RECONCILIATION_RELEASE_EVIDENCE.md`; `src/sidedeck/application/sd034_reconciliation_contract.py`; `tests/test_sd034_reconciliation_contract.py`.
- [x] **SD-035 | P0 | VERIFIED | deps: SD-034 | Alpaca PAPER account-separation comparison.** Executed exactly one `GET /v2/account` per authorized credential pair. Pair A returned HTTP 200 with a valid schema; Pair B returned HTTP 401; comparison is fail-closed `UNVERIFIED`, with 2/2 attempts consumed and no retry. No identity was retained and release remains `NO_GO`. **Evidence:** `docs/SD035_ALPACA_ACCOUNT_SEPARATION_RESULTS.md`; `src/sidedeck/application/sd035_account_separation.py`; `tests/test_sd035_account_separation.py`.
- [x] **SD-036 | P0 | VERIFIED | deps: SD-032, SD-033, SD-034 | eToro Demo primary-broker contract review and offline order desk.** Compared the existing read-only adapter with the current public eToro Demo API reference. Added a Demo-only route allowlist (Real permanently refused), long/unleveraged/limitIOC open bodies, strict `orders:lookup` and close parsers, write-ahead lineage (referenceId→orderId→positionId), recovery only by referenceId lookup, baseline-proof close protection, mirror-child discrepancies and a simulator-only desk reusing the SD-032 outbox and SD-033 approvals/kill-switch. **Accept:** offline tests plus exact-HEAD CI. **Evidence:** `docs/SD036_ETORO_DEMO_CONTRACT_REVIEW.md`, `docs/ADR-003-etoro-demo-primary-broker.md`, `src/sidedeck/domain/etoro_demo_orders.py`, `src/sidedeck/application/sd036_etoro_demo_desk.py`, `tests/test_sd036_etoro_demo_desk.py`. Exact-head CI `39637245551` passed on `d50bdd0` (657 passed incl. PostgreSQL).
- [x] **SD-037 | P0 | VERIFIED | deps: SD-036 | eToro Demo desk hardening (R3/R4).** Client-side enforcement of the documented shared write budget (20/60 s) and read budget (60/60 s), persisted across restarts, plus offline close-order recovery via `orders:lookup?referenceId=` behind a fail-closed `NOT_VERIFIED` flag. **Accept:** adversarial tests (burst, restart, clock skew, lost close response); still no HTTP transport. **Done:** `DemoRateBudget` (refuses, never retries; clock-regression refusal) and `recover_close_from_snapshot` from documented `/pnl` data; lookup-based close recovery kept `NOT_VERIFIED`. Tests in `tests/test_sd036_etoro_demo_desk.py` (SD-037 section). Exact-head CI `39638921652` passed on `d353a4e` (667 passed incl. PostgreSQL).
- [x] **SD-038 | P0 | VERIFIED | deps: SD-036 | Authorized eToro Demo baseline re-reconciliation (R1).** The owner authorized exactly one `GET /api/v1/trading/info/demo/pnl` (0 retries, $0). The new runner reserves a persistent 1-attempt budget before sending and opens the baseline DB read-only with a before/after SHA-256 check. **Result:** HTTP 200, schema PASSED, 4 current positions, **4/4 protected baseline MATCHED**, 0 discrepancies, no mirrors, no extra/unattributed positions, no pending orders, baseline DB unchanged; 1/1 attempt consumed; authorization expired. **Evidence:** `docs/SD038_ETORO_BASELINE_RECONCILIATION.md`, `src/sidedeck/application/sd038_etoro_baseline_reconcile.py`, `tests/test_sd038_etoro_baseline_reconcile.py`; ignored counter-only budget `data/sd038-auth-budget.sqlite3`. Exact-head CI `39643592521` passed on `f1ea66b1a4bf8bf08c3303940eeded731dd85d97` (685 passed incl. PostgreSQL): https://github.com/smbabalola/sidedeck/actions/runs/39643592521.
- [x] **SD-039 | P1 | VERIFIED | deps: SD-036, SD-031 | eToro Demo desk status on the release-gate surface.** Add a sanitized eToro section to the SD-030 report and dashboard: broker priority, `NO_GO`, Real `PERMANENTLY_EXCLUDED`, simulator-only transport, residual risks by ID. No IDs, values or order controls. **Done:** code-derived `etoro_demo_status()` in the SD-030 report, `/api/research/release-gate` (a local file cannot override it; forgery test) and the dashboard panel. Frontend build passed. Exact-head CI `39638921652` passed on `d353a4e` (667 passed incl. PostgreSQL).
- [x] **SD-041 | P1 | VERIFIED | deps: SD-037 | Dormant eToro Demo transport design review (R5/R6).** Written threat model and interface spec for a future HTTP transport: header handling, no-redirect, size and timeouts, sanitized errors, idempotent `x-request-id` reuse only on the same body, plus a live-schema verification checklist. No HTTP client code is merged and no request is made. **Accept:** doc plus an AST guard test proving that no Demo-write HTTP transport exists in `src/`. **Done:** `docs/SD041_ETORO_DEMO_TRANSPORT_REVIEW.md`; `tests/test_sd041_no_demo_write_transport.py` (detection self-checked). Exact-head CI `39639242108` passed on `dfa665d` (669 passed).
- [x] **SD-042 | P1 | VERIFIED | deps: SD-036 | eToro credential policy.** **Superseded 2026-10-22 by [ADR-004](docs/ADR-004-single-etoro-demo-credential-pair.md):** one owner-accepted Demo Read/Write pair (`ETORO_DEMO_TRADE_*`) for GET-only monitoring and future approved execution; legacy names refused if also set; R9 owner-accepted with compensating controls; monitoring CLIs use `monitoring_credentials`. Original two-key design below: The owner confirmed 2026-10-21 that the current key is Demo + Read/Write (R2 partly closed; IP whitelist, expiry and write capability unverified; new R9: the monitoring key is Read/Write). `assess_roles`/`require_separated_execution_credentials` refuse shared or missing roles (distinct user keys) and never output values. **Evidence:** `src/sidedeck/application/sd042_etoro_credential_roles.py`, `tests/test_sd042_sd043_etoro_review.py`. Exact-head CI `39645362815` passed on `d0cc9c4` (695 passed).
- [x] **SD-043 | P1 | VERIFIED | deps: SD-036 | Sanitized live-schema diagnostics (R6).** `response_shape_issues` reports field paths and JSON types (and casing drift) for open/lookup/close/close-info responses, never values. Simulator responses are checked against the documented shapes. **Evidence:** `src/sidedeck/domain/etoro_demo_orders.py`, `tests/test_sd042_sd043_etoro_review.py`. Exact-head CI `39645362815` passed on `d0cc9c4` (695 passed).
- [ ] **SD-044 | P1 | BLOCKED_OWNER | deps: SD-042, SD-043, SD-045 | First eToro Demo order pilot (dormant proposal).** 1 open + 1 close, max 11 requests, kill criteria and sanitized evidence. **Evidence:** `docs/SD044_ETORO_DEMO_PILOT_PROPOSAL.md`. **Blocker:** prerequisites P1–P5 (separate Read-only monitoring key, IP/expiry, reviewed transport, real signature verifier, pilot capital) and explicit owner pilot approval. **2026-10-21:** the owner reviewed the proposal and recommended the parameters now recorded in §2 (USD 50, 1 position, 1×, limitIOC ≤0.5 %, 11 requests / 2 writes, 0 write retries). Added the rule that an unconfirmed close yields `UNRESOLVED_OPERATOR_INTERVENTION_REQUIRED` plus the kill-switch, never `COMPLETE`. The owner signers file goes in ignored `data/approval_allowed_signers` (dedicated key). Waiting on the owner for P1, P2 and P4 setup; Codex then runs a no-network config check, the P3 transport review and the release checklist. No new development cycle until then. **Offline check, 2026-10-21 (no network):** the Demo Read/Write pair is configured as `ETORO_DEMO_TRADE_*`. The Demo Read-only monitoring pair is not yet created (gate: `MONITOR_CREDENTIAL_NOT_CONFIGURED`). The signers file `data/approval_allowed_signers` is not yet present. IP whitelist and expiry are owner-attested. Monitoring reads (`etoro_demo_portfolio`, SD-038 runner) now fail closed for lack of `ETORO_API_KEY`/`ETORO_USER_KEY`, which is intended. The owner confirmed Demo only, with no Real key.
- [x] **SD-046 | P0 | VERIFIED | deps: SD-036, SD-043, SD-044 | Offline eToro Demo pilot runner.** Orchestrates the SD-044 plan through the desk: per-route persistent caps (pnl 3, open 1, lookup 3, close 1, close-info 3 = 11), shape checks on every response, scope validation (≤ USD 50, ≤ 0.5 % premium, instrument not in baseline), separately signed close approval, and `COMPLETE` only when the close is FILLED, the final snapshot is MATCHED and no SideDeck positions remain. Lost, pending or partial closes and shape drift give `UNRESOLVED_OPERATOR_INTERVENTION_REQUIRED` with the kill-switch tripped and the position kept OPEN. Simulator only; the wrapper never upgrades a live transport. **Evidence:** `src/sidedeck/application/sd046_etoro_demo_pilot.py`, `tests/test_sd046_etoro_demo_pilot.py` (18). CI passed (`39771232748`, `10066dc`; re-verified `39775790500`).
- [x] **SD-048 | P0 | VERIFIED | deps: SD-046, SD-045 | C7 eToro Demo transport and C8 signed one-time pilot release (owner-authorized build, offline only).** The transport is locked (`NETWORK_TRANSPORT_ENABLED=False`, injected mock openers only, real openers refused). It enforces Demo routes only, signed per-release caps in a persistent ledger, order bodies equal to the signed intent, no redirects or retries, and outcome-unknown on any write failure. C8 requires an SSH signature in a dedicated namespace **plus** independent runtime gates, and each release is single-use. The independent security review (no critical findings) had all HIGH/MEDIUM items fixed with regression tests. **Evidence:** `docs/SD048_C7_C8_TRANSPORT_AND_PILOT_RELEASE.md`, `src/sidedeck/infrastructure/etoro_demo_write_transport.py`, `src/sidedeck/application/sd048_pilot_release.py`, `tests/test_sd048_c7_c8.py`. Local: 801 passed, 1 skipped. Exact-head CI `39775790500` passed on `8d43edb` (802 passed): https://github.com/smbabalola/sidedeck/actions/runs/39775790500.
- [x] **SD-050 | P0 | CLOSED | deps: SD-049 | MSFT eToro instrument ID (first lookup).** Consumed 2026-10-22: HTTP 200, candidate rejected by the then-strict type check; ID not retained. Permanently refused (`EXHAUSTED_LOOKUP_IDS`). Superseded by SD-052. **Evidence:** `docs/SD050_SD051_MSFT_LOOKUP_AND_FRESH_PRICE.md`.
- [x] **SD-052 | P0 | VERIFIED | deps: SD-050 | MSFT instrument ID resolved = 1004.** Second owner authorization; committed launcher `sd052_msft_lookup_cli` (`a4e9a18`, CI `39800966856` passed) run by the owner: 1/1 GET, HTTP 200, `RESOLVED_PARTIALLY_VERIFIED` (exchange Nasdaq, issuer Microsoft, listed, visible VERIFIED; type and currency UNVERIFIED), no baseline conflict, lookup lock restored, 0 orders. SD-052 now exhausted in code. **Evidence:** `docs/SD052_SD053_MSFT_ID_AND_PILOT_INTENT.md`, ignored `data/sd052-msft-instrument.json`.
- [ ] **SD-053 | P0 | BLOCKED_OWNER | deps: SD-052 | MSFT pilot intent prepared for signature.** Schema v2: 1004, 0.09 units, signed max 552.56 (≤ USD 49.73), limitIOC 1× buy, window Fri 2026-10-23 14:00–15:30 UTC, 12 requests / 2 writes, digest `71e111b3a8806dc9b8e59d96ce1ef6e6a0b64dc2b00363465244acccaad09a62`. Preflight now aborts on conflicting broker type/currency labels and reports BROKER_VERIFIED / DERIVED. **Blocker:** owner SSH signature (namespace `sidedeck-etoro-pilot-release`).
- [ ] **SD-054 | P0 | IMPLEMENTED | deps: SD-053 | Supervised pilot operator runner.** `sd054_pilot_operator.run_pilot`: signed release (+runtime gates, single use) → desk with policy = intent → preflight → owner-signed open approval (5 min TTL) → open → owner-signed close approval → close → final reconcile; COMPLETE only on FILLED + MATCHED + 0 SideDeck positions, else UNRESOLVED + kill-switch. Transport arrives via an injected factory, so `src` still never constructs the HTTP order transport (SD-041 guard unchanged); `main()` refuses `REFUSED_LOCKED` before reading secrets or consuming the release. 8 end-to-end tests over the real transport code + offline simulator (COMPLETE with 2 writes; declined open → 0 orders; declined close → UNRESOLVED; ask > signed max → abort pre-write; wrong key/namespace/gate refused; single use). **Next:** reviewed lock-lift commit (production factory + interactive signing prompts + `NETWORK_TRANSPORT_ENABLED` + guard update) with an independent security review, only on the owner's explicit execution authorization.
- [x] **SD-051 | P0 | VERIFIED | deps: SD-048 | Fresh-price and eligibility preflight; 12-request budget.** The signed intent carries the units and a max limit. The preflight does pnl → Demo eligibility (fractional, minimum, units-based, long 1× real) → realtime rates ≤ 60 s → limit = min(max, ask × 1.005). The owner signs the exact open approval; the desk re-checks the evidence. The independent review had 1 HIGH, 2 MEDIUM and 4 LOW findings, all fixed with tests. Local: 836 passed, 1 skipped. Exact-head CI `39782565600` passed on `5fb32ff` (837 passed).
- [ ] **SD-049 | P0 | BLOCKED_OWNER | deps: SD-047, SD-048 | MSFT pilot release checklist.** B1 RESOLVED (1004), B2 RESOLVED (no conflict), B3/B4 automated preflight gates, B5 SET (Fri 2026-10-23 10:00–11:30 ET); type/currency verified at preflight. Remaining: owner intent signature (SD-053), operator runner (SD-054), reviewed lock lift plus explicit execution authorization. **Evidence:** `docs/SD049_MSFT_PILOT_RELEASE_CHECKLIST.md`.
- [ ] **SD-047 | P0 | BLOCKED_OWNER | deps: SD-046 | Pilot release checklist.** C1, C2, C4, C5 and C6 done; C3 (signing key), C7/C8 built (locked; SD-048), C9 (≤ USD 50 allocation), C10 (instrument and its eToro ID) and C11 (date window) pending owner. **Evidence:** `docs/SD047_ETORO_DEMO_PILOT_RELEASE_CHECKLIST.md`.
- [x] **SD-045 | P1 | VERIFIED | deps: SD-033 | Real signature verifier for paper approvals (P4).** Replace test-only verifier lambdas with an owner-held asymmetric key scheme (Ed25519 public key in config; the private key never on disk in the repo). Offline tests for wrong key, tampered scope, expiry and replay. **Done (no new dependency):** `SshSignatureVerifier` verifies OpenSSH signatures (`ssh-keygen -Y verify`, namespace `sidedeck-paper-approval`) against an owner `allowed_signers` public key. Wrong key, digest, namespace or principal, tampered, garbage, oversized or non-ASCII signatures all fail closed; integrates with `ApprovalKillSwitch`. **Evidence:** `src/sidedeck/application/sd045_ssh_approval_verifier.py`, `tests/test_sd045_ssh_approval_verifier.py` (throwaway tmp keys). The owner still has to provide their public key (pilot P4). Exact-head CI `39646091812` passed on `3a68ed0` (706 passed; the SD-045 tests ran, not skipped).
- [x] **SD-040 | P2 | VERIFIED | deps: none | eToro Agent Portfolios evaluation.** Decision `NOT_ADOPTED_PENDING_EVIDENCE`: documented Real-account scopes, funded by deducting the caller balance, implemented as a copy/mirror; routes refused by the allowlist (tested). **Evidence:** `docs/SD036_ETORO_DEMO_CONTRACT_REVIEW.md` §5.

## Session control and next autonomous batch

**Batch Z (2026-10-22; ADR-004 single Demo credential pair):**

- Owner decision: one eToro Demo Read/Write pair for monitoring and future approved execution; no second key; no Real key. R9 is owner-accepted. SD-044 P1 **not yet satisfied**: the offline check found a second, different pair under the legacy names, so the policy refuses (`EXTRA_CREDENTIAL_NAMES_REFUSED`). The owner must remove whichever pair is not the Demo Read/Write one.
- Local verification: 708 passed, 1 skipped; Ruff passed; mypy 133 files. No network request, credential read for use, or order.
- Exact-head CI `39769758027` passed on `52d121a` (709 passed). At 12:22 the owner removed the legacy names, so P1 is satisfied. Added the SD-046 offline pilot runner (726 passed locally) and the SD-047 release checklist; the remaining items are owner actions (C3, C7 build approval, C8, C9–C11).

**Batch Y (2026-10-21; owner key confirmation, SD-042/043 implemented, SD-044 proposed):**

- The owner confirmed the eToro key is Demo with Read/Write permission. R2 is partly closed; the IP whitelist, expiry and write capability remain unverified. Added R9 (monitoring key is Read/Write); a separate Read-only monitoring key is recommended.
- Added the credential-role separation gate and sanitized response-shape diagnostics, and drafted the dormant first-order pilot proposal (11-request cap, 2 writes).
- Local verification: 694 passed, 1 skipped; Ruff passed; mypy 132 files. No network request, credential read or order.
- Exact-head CI `39645362815` passed on `d0cc9c4` (695 passed). SD-045 has since been implemented (see board).

**Batch X (2026-10-21; SD-038 authorized read consumed):**

- Executed exactly one owner-authorized eToro Demo `/pnl` GET: HTTP 200, `MATCHED`, 4/4 protected baseline positions, 0 discrepancies, no mirrors or extra positions; the baseline DB was byte-identical afterwards. 1/1 attempts consumed; no retry, order, close, other endpoint, Alpaca/Saxo request or paid call. R1 is closed.
- Remaining eToro release blockers: R2 key permission scope (portal UI), R3 close lookup, R5 transport review, R6 live order schemas, R8 capital, G4 owner order release (SD-011) and soak (SD-013). Execution `NO_GO`/`DISABLED`.
- Next: offline work only under the steering file. Any further authenticated request or Demo order needs a new bounded owner authorization.

**Batch V (2026-10-21; broker priority change, SD-036 implemented, SD-040 verified):**

- The owner made eToro Demo the primary paper broker and Alpaca PAPER secondary (ADR-003). eToro Real is permanently excluded.
- Reviewed the existing eToro integration against the public API reference (docs only; no authenticated request). Built the offline desk, strict order/lookup/close contract and verified lineage. Added per-position `mirrorID` parsing as a reconciliation discrepancy.
- Local verification: 656 passed, 1 skipped (PostgreSQL, CI-only); Ruff passed; mypy passed across 130 source files; SQLite Alembic upgrade passed. SD-036 tests: 61 passed.
- Exact-head CI `39637245551` passed on `d50bdd0cbcee891edb0467d9a543a7aa4a7710ef`: https://github.com/smbabalola/sidedeck/actions/runs/39637245551 (657 passed incl. PostgreSQL; Ruff, mypy 130 files; only the existing Node 20 warning).
- No credential read, authenticated eToro/Alpaca request, order, position change, paid call or Agent Portfolio call occurred.
- Next READY: SD-037, then SD-039. SD-038 awaits a bounded owner authorization.

**Batch W (2026-10-21; SD-037 and SD-039 implemented):**

- Added persisted enforcement of the documented eToro quotas, snapshot-based recovery for lost close responses, and a code-derived eToro Demo status on the release-gate report, API and dashboard.
- Local verification: 666 passed, 1 skipped; Ruff passed; mypy 130 files; SQLite Alembic upgrade; frontend production build passed.
- No network broker call, credential read or order.
- Exact-head CI `39638921652` passed on `d353a4e39e857ad252314a78484e6d57930ca580`: https://github.com/smbabalola/sidedeck/actions/runs/39638921652 (667 passed; mypy 130 files; only the Node 20 warning).
- Remaining eToro risks: R1/R2 (need SD-038 owner read and portal check), R3 lookup path, R5 no released transport, R6 live schema, R8 no capital. Next safe work: SD-041 (READY), an offline Demo transport contract spec and threat model, kept dormant and with no HTTP client, to prepare the R5 review.
- **SD-041 verified** (CI `39639242108`, https://github.com/smbabalola/sidedeck/actions/runs/39639242108). Safe offline eToro work is now at the owner boundary. Remaining eToro items need SD-038 (one owner-run `/pnl` GET plus a portal key check) and, later, a separate Demo order release (SD-011). Independent non-eToro blockers (SD-004, SD-008, SD-013) are unchanged.

**Batch N (2026-10-21; SD-027 and SD-028 verified):**

- Added an independent offline paper-readiness matrix. Safe boundaries pass,
  but duplicate-order, broker-fill reconciliation, approval-signature,
  kill-switch and account-separation gates fail; overall status is `NO_GO` and
  paper submission remains disabled.
- Added deterministic SPY/QQQ joint economics over 1,254 overlapping sessions:
  50/50 weights, 0.947673 return correlation, 1.804260 equal-weight ending
  equity, 30.33% maximum drawdown and 50% maximum concentration. Turnover,
  costs and regime sensitivity remain explicitly unassessed.
- Focused verification: 2 passed. Full local verification: 572 passed,
  1 skipped, 3 warnings; Ruff, mypy across 121 source files, SQLite Alembic
  upgrade and frontend build passed. No network, credential, paid-data/model,
  account, broker or trading action occurred. Exact-head GitHub CI
  `39587401345` passed on `369f54dc7c670c2591262eb1c0f8f4a244da17c5`:
  https://github.com/smbabalola/sidedeck/actions/runs/39587401345. CI emitted
  only the existing Node 20 and ubuntu-latest migration warnings.
- SD-029 is now the next READY package because SD-027 is verified.

**Batch O (2026-10-21; SD-029 verified):**

- Added a disposable in-memory paper-release rehearsal covering explicit
  external approval records, simulated submission/acknowledgement, partial and
  complete fills, exit lineage, idempotency conflicts, rollback and emergency
  stop. No HTTP, credentials, broker state or order action exists in the
  harness.
- Full local verification: 575 passed, 1 skipped, 3 warnings; Ruff, mypy
  across 122 source files, SQLite Alembic upgrade and frontend build passed.
  No external access or trading action occurred. Exact-head GitHub CI
  `39587901482` passed on `8e712ff9728add3be67b2e73a5e093dad2e9c3b1`:
  https://github.com/smbabalola/sidedeck/actions/runs/39587901482. CI emitted
  only the existing Node 20 and ubuntu-latest migration warnings.
- Next safe batch: SD-030 sanitized release-gate evidence report.

**Batch P (2026-10-21; SD-030 verified):**

- Added a sanitized machine-readable paper-release gate report that combines
  SD-027 `NO_GO` controls with SD-029 rehearsal evidence. It requires separate
  owner approval, preserves the protected baseline, and rejects any non-NO-GO
  readiness or enabled broker execution.
- Full local verification: 577 passed, 1 skipped, 3 warnings; Ruff, mypy
  across 123 source files, SQLite Alembic upgrade and frontend build passed.
  No network, credentials, account access, paid call, broker or trading action
  occurred. Exact-head GitHub CI `39588376589` passed on
  `1020be8d6232b4b14024a1731a962f60e2230ace`:
  https://github.com/smbabalola/sidedeck/actions/runs/39588376589. CI emitted
  only the existing Node 20 and ubuntu-latest migration warnings.
- Next safe batch: SD-031 operator evidence surface.

**Batch Q (2026-10-21; SD-031 verified):**

- Added a read-only `/api/research/release-gate` route and dashboard evidence
  panel for the sanitized SD-030 report. Missing, malformed, oversized or
  release-enabled inputs fail closed to `NO_GO`, `release_enabled=false` and
  `paper_order_submission=DISABLED`; only an allowlisted rehearsal summary is
  exposed and no credentials, account identifiers or order controls can pass
  through.
- Full local verification: 579 passed, 1 skipped, 3 warnings; Ruff passed,
  mypy passed across 123 source files, SQLite Alembic upgrade passed and the
  frontend production build passed. No network, credentials, account access,
  paid call, broker or trading action occurred. The initial combined build
  invocation was corrected to run npm from `web/`; the successful build is
  the authoritative result.
- SD-004 remains `BLOCKED_EXTERNAL`; SD-008, SD-011 and SD-013 remain
  `BLOCKED_OWNER`. Paper-order execution remains disabled. Next safe work is
  exhausted pending new independent market evidence or owner release gates.
- Exact-head GitHub CI `39588995875` passed on
  `54d0ba7841c8502fd901efd350a3515240b2dd14`:
  https://github.com/smbabalola/sidedeck/actions/runs/39588995875. CI emitted
  only the existing Node 20 and ubuntu-latest migration warnings.

**Batch R (2026-10-21; SD-032 through SD-034 verified):**

- Implemented durable offline paper-intent persistence, verifier-only scoped
  approvals, restart-safe emergency stop and mock-only broker reconciliation.
  Adversarial tests cover conflicting client IDs, invalid transitions,
  partial-to-full fill replay, signature/identity/expiry/replay refusal,
  kill-switch persistence and separate clearance, duplicate events, missing
  sequence numbers, invalid ordering and exits beyond fills.
- Added the dormant owner-read proposal only; it specifies three bounded
  read-only Alpaca PAPER GETs but was not executed. No authenticated account
  request, order, paid provider call, credential read or live/paper execution
  occurred. Paper release remains `NO_GO`; broker transport remains disabled.
- Full local verification: 586 passed, 1 skipped, 3 warnings; Ruff passed,
  mypy passed across 126 source files, SQLite Alembic upgrade passed and the
  frontend production build passed. PostgreSQL remains CI/container-only.
- SD-004 remains `BLOCKED_EXTERNAL`; SD-008, SD-011 and SD-013 remain
  `BLOCKED_OWNER`. Meaningful safe implementation work is exhausted at this
  boundary; next action is a new independent evidence or owner-authorization
  decision, not another authenticated request.
- Exact-head GitHub CI `39590894464` passed on
  `2e007911f7cd1b1aa2c520210fd4e1abb8994a4b`:
  https://github.com/smbabalola/sidedeck/actions/runs/39590894464. CI emitted
  only the existing Node 20 and ubuntu-latest migration warnings.

**Batch S (2026-10-21; SD-034 authorized read-only verification consumed):**

- Executed exactly three authenticated Alpaca PAPER GETs under the bounded
  owner authorization: `/v2/account`, `/v2/positions` and `/v2/orders`.
  Each returned HTTP 200 with a valid coarse schema. The account reported
  `ACTIVE`/`USD`; zero positions and zero orders were returned. The persistent
  attempt budget records 3 of 3 consumed, with no retry or additional path.
- Account identity/separation remains `UNVERIFIED`: the account identifier
  was withheld and no independently supplied mapping or second-account
  comparison was authorized. This does not establish release readiness.
  Paper release is still `NO_GO`; broker execution is `DISABLED`.
- Raw responses, credentials, headers, account/order/position identifiers,
  balances, quantities and prices were not persisted or printed. No order,
  eToro request, paid call, monitoring loop or live trading occurred.
- **Evidence:** `docs/SD034_ALPACA_READONLY_VERIFICATION.md` and the bounded
  one-shot verifier in `src/sidedeck/application/sd034_alpaca_one_shot.py`.
  The ignored local budget is `data/sd034-auth-budget.sqlite3` and contains
  counters only. The authorization is exhausted; no further authenticated
  request is permitted without a new bounded owner decision.
- Exact-head GitHub CI `39593173513` passed on
  `811f3184f0f6dd8d45bc6585f0875bde4a00fcf4`:
  https://github.com/smbabalola/sidedeck/actions/runs/39593173513. CI emitted
  only the existing Node 20 and ubuntu-latest migration warnings.

**Batch T (2026-10-21; SD-035 proposal prepared, no request executed):**

- Prepared the exact two-request account-separation scope: one `/v2/account`
  GET for each configured Alpaca PAPER credential pair, with in-memory
  identity comparison and only `DISTINCT`, `SAME` or `UNVERIFIED` output.
- No authenticated request, credential read, account identifier access,
  order, eToro request, paid call or trading action occurred. Paper release
  remains `NO_GO` and broker transport remains `DISABLED`.
- Next action: obtain a separate explicit owner authorization for this exact
  two-request scope, or continue offline work; do not reuse SD-034's exhausted
  three-request authorization.
- Exact-head GitHub CI `39594454335` passed on
  `1d9991a27c5dcfb70c69e331eadb2ca72dde8d2a`:
  https://github.com/smbabalola/sidedeck/actions/runs/39594454335. CI emitted
  only the existing Node 20 and ubuntu-latest migration warnings.

**Batch U (2026-10-21; SD-035 authorized comparison consumed):**

- Executed exactly two authenticated Alpaca PAPER `GET /v2/account` attempts:
  Pair A (`ALPACA_API_KEY`/`ALPACA_API_SECRET`) returned HTTP 200 with a
  valid schema; Pair B (`ALPACA_API_KEY2`/`ALPACA_API_SECRET2`) returned HTTP
  401. The comparison is `UNVERIFIED`; the second attempt was not retried.
- No account identity, credential, header, balance or raw response was
  persisted or printed. The two-attempt authorization is exhausted. Paper
  release remains `NO_GO`, broker execution remains `DISABLED`, and no order,
  eToro/Saxo request, paid call, monitoring or live trading occurred.
- **Evidence:** `docs/SD035_ALPACA_ACCOUNT_SEPARATION_RESULTS.md` and the
  ignored counter-only budget `data/sd035-auth-budget.sqlite3`. Account
  separation remains unresolved and requires a new bounded authorization if
  another broker check is ever needed.
- Exact-head GitHub CI `39595852824` passed on
  `a79b726ad6f92fbf45bc7dcc0ddd1d5e2faa1d89`:
  https://github.com/smbabalola/sidedeck/actions/runs/39595852824. CI emitted
  only the existing Node 20 and ubuntu-latest migration warnings.
- Final evidence-alignment commit: `6aca8995b482da82991b81494971c92540b51775`;
  exact-head GitHub CI `39596052580` passed:
  https://github.com/smbabalola/sidedeck/actions/runs/39596052580. CI emitted
  only the existing Node 20 and ubuntu-latest migration warnings.
- Final SD-035 HEAD `fece1aaaf95e6f9b5cb857930af529bb6ecced99` exact-head
  GitHub CI `39596254346` subsequently passed:
  https://github.com/smbabalola/sidedeck/actions/runs/39596254346. The
  account-separation result remains `UNVERIFIED` because Pair B returned HTTP
  401; do not repeat the exhausted authorization. Next action is owner-side
  dashboard/configuration review of the second paper credential pair, followed
  by a new bounded authorization only if identity comparison is still needed.

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

**Batch G (verified; SD-014–SD-019 real-data strategy engine) — 2026-10-21**

- Implemented and tested the four-strategy catalogue, reusable normalized-bar
  boundary, chronological 80/20 selection with locked OOS, embargo and
  walk-forward evaluation, fee/slippage sensitivity, parameter surfaces,
  acceptance statuses, equal-risk proposal portfolio simulation, correlation
  controls, attribution and configurable drawdown kill-switch simulation.
- Added the sanitized strategy-catalogue API and dashboard surface. It shows
  metadata and acceptance state only; it cannot create positions, orders,
  balances or broker state.
- Existing ignored MSFT SIP evidence was processed offline: 59 observations;
  channel mean reversion 0 trades, liquidity-sweep reversal 0 trades,
  moving-average trend 1 trade and buy-and-hold 1 trade. All four are
  `INSUFFICIENT_DATA`; no genuine profitability or five-year claim was made.
- Full local verification: 554 passed, 1 skipped, 3 warnings; Ruff passed;
  mypy passed across 114 source files; SQLite Alembic upgrade and frontend
  production build passed. Exact-HEAD GitHub CI `39576345876` passed on
  `b54fc1912348be1ed6580d7e6facfac58a1a05e4`:
  https://github.com/smbabalola/sidedeck/actions/runs/39576345876. CI emitted
  only Node 20 and ubuntu-latest migration warnings.
- No authenticated data request, paid data/model call, credential read,
  account/portfolio endpoint, eToro request, paper order, real order or
  production release occurred. SD-004, SD-008, SD-011 and SD-013 retain their
  existing external/owner blockers.
- Next batch: apply the engine to a lawful multi-year owner-supplied dataset
  or continue independent strategy-testing infrastructure; 59 sessions remain
  correctness evidence only.

**Batch H (2026-10-21; SD-020 and SD-021 verified):**

- Read-only local inventory found no SPY/QQQ history or five-year MSFT series.
  It found only the existing 59-bar MSFT SIP evidence and an unrelated
  701-bar SOFI IEX bundle. No raw data was copied or committed.
- Used the exact new authorization once: SPY, QQQ and MSFT; 2021-10-21 through
  2026-10-20; daily SIP; split-adjusted; USD; maximum 20 requests per ticker;
  local-only manifests. One HTTP 200/page per ticker consumed 3/60 requests.
- Added crash-safe global/per-ticker budgets, redirect rejection, exchange
  identity normalization, 2021–2026 session validation, sanitized admission
  reports, closed-trade metric accounting and read-only dashboard summaries.
- Ran four strategies per instrument with locked OOS, 9-cell parameter
  surfaces, in-sample-only selection, four walk-forward windows and proposal
  portfolio controls. Results and hashes: `docs/SD021_RESULTS.md`.
- Full local verification: 562 passed, 1 skipped, 3 warnings; Ruff passed;
  mypy passed across 116 source files; SQLite Alembic upgrade and frontend
  production build passed. Exact-head GitHub CI `39579019726` passed on
  `05289068e40daa83c96dea3443c272290dd6f6bf`:
  https://github.com/smbabalola/sidedeck/actions/runs/39579019726. CI emitted
  only the existing Node 20 and ubuntu-latest migration warnings.

**Batch J (2026-10-21; SD-023 verified):**

- Added an offline independent benchmark audit that compounds the saved
  close-to-close prices, calculates price-only drawdown, and reconciles each
  SPY/QQQ/MSFT ending equity to the corresponding SD-021 research report with
  zero delta.
- Confirmed MSFT's limited existing split/dividend record is compatible with
  the split-adjusted, dividend-excluded close basis. SPY/QQQ ETF corporate
  actions remain `NOT_ASSESSED`; total-return values remain `UNAVAILABLE`.
- Focused verification: 2 passed. No network, credential, paid-data/model,
  account, broker or trading action occurred. Next safe batch: SD-024 ETF
  distribution evidence boundary.
- Full local verification: 565 passed, 1 skipped, 3 warnings; Ruff, mypy,
  SQLite Alembic upgrade and frontend production build passed. Exact-head
  GitHub CI `39584305784` passed on `b2add69a7f554891558f4dbbfbe0b2b3c9cac1a7`:
  https://github.com/smbabalola/sidedeck/actions/runs/39584305784. CI emitted
  only the existing Node 20 and ubuntu-latest migration warnings.

**Batch K (2026-10-21; SD-024 verified):**

- Added a transport-free, fail-closed parser for owner-supplied/public SPY and
  QQQ split/distribution evidence. It validates source class, split ratios,
  positive distributions, ex-date/payment-date ordering and duplicates.
- Explicitly separates price-only benchmark support from total-return
  availability. No ETF records were available, so SPY/QQQ remain
  `NOT_ASSESSED` and no total-return claim was emitted.
- Full local verification: 569 passed, 1 skipped, 3 warnings; Ruff, mypy
  across 119 source files, SQLite Alembic upgrade and frontend production
  build passed. No network, credentials, paid data/model, account, broker or
  trading action occurred. Exact-head CI is pending for this batch.
- Next safe batch: SD-025 benchmark/report integration.
- Exact-head GitHub CI `39584782646` passed on `d317d11e069c7951105d044e68625bfb9c9b0c74`:
  https://github.com/smbabalola/sidedeck/actions/runs/39584782646. CI emitted
  only the existing Node 20 and ubuntu-latest migration warnings.

**Batch L (2026-10-21; SD-025 verified locally):**

- Integrated optional local SD-023 benchmark audits into the sanitized strategy
  validation summary and added the `--strategy-audit` dashboard API input.
  Missing or malformed audits fail closed; total-return `UNAVAILABLE` remains
  explicit and cannot become investor-return language.
- Full local verification: 570 passed, 1 skipped, 3 warnings; Ruff, mypy
  across 119 source files, SQLite Alembic upgrade and frontend production
  build passed. No network, credential, paid data/model, account, broker or
  trading action occurred. Exact-head CI is pending for this batch.
- Next safe batch: SD-026 dashboard benchmark presentation.
- Exact-head GitHub CI `39585241005` passed on `6d47cfac0768463580fa78d8b8d50d3635490201`:
  https://github.com/smbabalola/sidedeck/actions/runs/39585241005. CI emitted
  only the existing Node 20 and ubuntu-latest migration warnings.

**Batch M (2026-10-21; SD-026 verified locally):**

- Added a read-only dashboard benchmark-evidence panel showing the explicit
  price-only convention, corporate-action status and `UNAVAILABLE` total
  return wording. It contains no recommendation, allocation or order control.
- Frontend production build passed with Vite 6.4.4; the API and Python
  regression suite remain covered by the preceding CI-verified head. No
  external access or trading action occurred. Exact-head CI is recorded below.
- Next safe work is exhausted at the current evidence boundary: SD-004,
  SD-008, SD-011 and SD-013 remain blocked by independent data/provider or
  owner release gates. Preserve SD-027 as a future derived task for local
  dashboard/API UI verification if a browser test harness is added.
- Exact-head GitHub CI `39586071624` passed on `249f97e83876fcfbc3412200a6946b814740c8c0`:
  https://github.com/smbabalola/sidedeck/actions/runs/39586071624. CI emitted
  only the existing Node 20 and ubuntu-latest migration warnings.
- No account, portfolio, order, eToro, Saxo, paid model/data or paper/real
  trading action occurred; credential values were not logged or exposed.
  SD-004 remains blocked by independent valuation evidence; next safe batch is
  SD-023 independent corporate-action and benchmark evidence.

**Batch I (2026-10-21; SD-022 verified):**

- Added an independent audit path for equity, drawdown, volatility, Sharpe,
  profit factor, completed round trips, exposure, fees/slippage and locked OOS
  results. Reconciled core metrics to the saved engine paths at zero or
  floating-point rounding deltas.
- Corrected the acceptance denominator to completed BUY→SELL trades. The five
  prior SD-021 whole-period screens reduce to two robustness survivors (SPY and
  QQQ channel mean reversion), one OOS rejection (MSFT channel mean reversion)
  and nine `INSUFFICIENT_DATA` outcomes.
- Verified in-sample-only selection, four chronological walk-forward windows,
  9-cell surfaces without OOS selection, portfolio weight sum and correlation
  limits. No cross-instrument diversification claim was made.
- No new authenticated/public network request, credential read, paid call,
  account access, order or trading action occurred. Next safe batch: SD-023.
- Full local verification: 563 passed, 1 skipped, 3 warnings; Ruff passed;
  mypy passed across 117 source files; SQLite Alembic upgrade and frontend
  production build passed. Exact-head GitHub CI `39583318757` passed on head
  `f3b466e13bd9a8c1c304baf7108545282da3fac5`:
  https://github.com/smbabalola/sidedeck/actions/runs/39583318757. CI emitted
  only the existing Node 20 and ubuntu-latest migration warnings.

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
