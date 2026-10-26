# SD-103 — Integrated trading pipeline (owner directive 2026-10-26)

**Directive:** stop building isolated pilots; integrate the existing components into one
pipeline that discovers, assesses, selects, executes (paper) and manages trades. Steering §16.

**Status in one line:** the pipeline runs end to end on one entry point. On genuine
SPY/QQQ/MSFT history it returns an honest **NO TRADE** because no strategy meets the admission
floor. On labelled fixtures it exercises the full lifecycle through simulated fills and exits,
with cash reconciled. No broker request, order, paid call or credential use occurred.

## 1. Run it

```powershell
# decision at the latest genuine cutoff (writes data/sd103/latest-run.json for the dashboard)
.venv\Scripts\python.exe -m sidedeck.application.sd103_trading_pipeline run
# forward test on genuine history: admission locked through 2026-04-30, replay 2026-05-01..2026-10-20
.venv\Scripts\python.exe -m sidedeck.application.sd103_trading_pipeline replay
# end-to-end acceptance harness on labelled synthetic fixtures (simulated fills)
.venv\Scripts\python.exe -m sidedeck.application.sd103_trading_pipeline acceptance
# dashboard: API (loopback 8765) then the web app -> "Trading engine" workspace
.venv\Scripts\python.exe -m sidedeck.application.p5_demo_dashboard_api --db data\etoro_demo.sqlite3
```

## 2. Component inventory (checked against code, 2026-10-26)

| Stage | Module | State before SD-103 | Now |
|---|---|---|---|
| Market data admission | `m2_market_data`, `us_equity_calendar`, SD-021 admitted bundles | verified, standalone | wired (stage A) |
| Scanner | `sd067_market_scanner` | implemented, fixture-only demo (SD-076) | wired on genuine bars |
| Strategy research | `sd014_strategy_engine`, `p5_sd021_research` | verified on genuine SPY/QQQ/MSFT, file-bound | wired via `research_payload` |
| Robustness admission | `sd022_robustness_audit` | verified, file-bound | wired via `audit_report` + SD-071 floor |
| Signals | `sd070_research_signal` | implemented | native strategy signals at the cutoff |
| AI agents | `sd069_agent_signal_adapters`, `p5_agents` | implemented; no authorized run | wired; UNAVAILABLE without an authorized record |
| Decision + sizing | `sd071_decision_engine` | implemented, used only in tests | wired |
| Risk halts | `sd072_track_risk_limits` | implemented | wired through the ledger |
| Paper ledger | `sd079_track_ledgers` | implemented, tests only | wired (SIMULATED_LOCAL) |
| Exits / position management | — | **missing** | `manage_position` + strategy exits |
| Performance attribution | — | **missing** | per strategy and version, benchmark, cash reconciliation |
| Dashboard | Milestone 3 workspaces | no pipeline view | `/api/pipeline/latest` + "Trading engine" |
| eToro Demo execution | SD-036/046/048/054 desk + transport | verified offline, single signed pilot | **not wired** to the pipeline (route NOT_RELEASED) |
| Autonomous policy | SD-063/SD-064/SD-074 | verified offline, not wired | unchanged; SD-074F is the next wiring step |
| UK BP pilot draft | `parked-uk-bp/` (untracked) | in progress | parked; BP is a connectivity test only |

Duplication avoided: no new strategy, decision, risk or ledger logic. Two file-bound functions
gained in-memory variants (`research_payload`, `audit_report`); behaviour is unchanged.

## 3. What the genuine data says

| Instrument | Strategy | Completed trades | Locked-OOS trades | OOS PF | Admission |
|---|---|---:|---:|---:|---|
| SPY | channel mean reversion | 61 | 12 | 5.99 | RESEARCH_ONLY (OOS trades < 30) |
| QQQ | channel mean reversion | 65 | 12 | 1.70 | RESEARCH_ONLY (OOS trades < 30) |
| MSFT | channel mean reversion | 76 | 14 | 0.38 | REJECTED |
| all | liquidity sweep / MA trend | 9–26 | 2–6 | — | RESEARCH_ONLY |

**Structural finding.** With the SD-021 80/20 split and the 2022–2026 verified calendar
(~1,250 sessions), a 5–15-day swing strategy cannot reach 30 locked-OOS trades on one
instrument; even an idealised synthetic series peaks near 18. The SD-071 floor is therefore
unreachable per instrument. It is **not** relaxed. Two owner-level options:

1. **More genuine evidence** — the SD-075B Alpaca SIP 20-instrument pilot (owner-signed data
   authorization, ≤ 24 requests) plus longer history where licensed.
2. **Pooled admission** — admit a strategy *version* on pooled locked-OOS trades across a
   point-in-time universe (e.g. 20 instruments × ~12), with per-instrument rejection still
   possible. This changes G3 methodology and needs explicit owner approval and review.

The latest genuine bar is 2026-10-20, so any decision today is also `STALE_FOR_EXECUTION`.

## 4. Fixture acceptance (plumbing only)

Three labelled synthetic instruments on real XNYS sessions. Production admission runs and
rejects; a `FIXTURE_ONLY_OVERRIDE_NOT_EVIDENCE` admission (refused for REAL_DATA) then lets
the execution half run: 33 simulated round trips over 2026-05-01..2026-10-23, stop, strategy
and time exits, cash reconciliation MATCHED, kill switch CLEAR. Negative tests: absent strategy
evidence, stale data, invalid prices, missing sessions, mixed data basis, missing owner
authorisation (all broker routes refused), insufficient capital, account mixing, duplicate
submission, IOC limit, partial fills, unexpected over-fill, broker outage, agent-only signal,
look-ahead (signal causality). `tests/test_sd103_trading_pipeline.py`, `tests/test_sd104_pipeline_api.py`.

Daily-bar position management is a monitoring rule, not a resting stop order: a gap fills at
the open, and if stop and target are both touched in one bar the stop is assumed (conservative).

## 5. Gates (2026-10-26)

| Gate | Status | Evidence / blocker |
|---|---|---|
| ENGINEERING | VERIFIED locally; exact-HEAD CI pending | 1,564 passed / 1 skipped; Ruff, mypy, tsc, build, Vitest 15, Playwright 36 passed |
| REAL_DATA | VERIFIED (daily, research-only limits) | SD-021 admitted bundles; split-adjusted, dividends excluded, corporate actions not independently verified |
| STRATEGY_ADMISSION | BLOCKED | no strategy ≥ 30 locked-OOS trades (§3) |
| AI_RESEARCH | BLOCKED | no authorized agent run (provider spend approval) |
| BROKER | BLOCKED | no broker-confirmed Demo round trip yet (MSFT pilot ready, unsigned) |
| PAPER_EXECUTION | BLOCKED | SD-074F policy-to-transport wiring + owner policy release |
| FORWARD_TESTING | NOT_ASSESSED | simulated replays only; no observed Demo trading |

## 6. Dependency-ordered plan (also the TODO board, Milestone 5)

1. **SD-103 pipeline** — IMPLEMENTED (this document).
2. **SD-104 dashboard** — IMPLEMENTED (read-only "Trading engine" workspace).
3. **SD-105 Stage 1 broker acceptance** — run the existing signed-intent MSFT Demo round trip
   (connectivity test, explicitly *not* a strategy recommendation). BLOCKED_OWNER.
4. **SD-106 admission evidence** — SD-075B genuine data for 20 instruments, then re-run SD-103;
   owner decision on pooled admission. BLOCKED_OWNER.
5. **SD-107 SD-074F** — wire SD-064 grants + SD-063 runtime + SD-074 sealed inputs into the eToro
   Demo transport as an SD-103 broker route, with send-time caps; independent review of the
   whole grant-to-order path. READY after SD-105 re-locks the transport.
6. **SD-108 broker quote/fill adapters** — seal eToro rates and lookups as SD-074 envelopes;
   replace "next open" simulation with fresh executable quotes. After SD-107.
7. **SD-109 scheduled runs** — SD-068 jobs call SD-103 `run` after each XNYS close (research
   only), persisted run history for the dashboard. READY (offline).
8. **SD-110 owner policy package** — ≤ 7-day, ≤ USD 1,000, ≤ USD 50/position SD-063 policy
   for admitted strategies only. After SD-105, SD-106, SD-107 and review.
9. **SD-111 forward testing** — ≥ 1 month observed Demo trading with suspension criteria.

## 7. The one owner approval for the next actual broker action

**Stage 1 broker acceptance = the prepared MSFT eToro Demo round trip** (pilot
`af2213c5-95c4-4207-a119-44df0ad0f78b`, digest
`1ab4d2c8f85c94ef6fca78164b3e1e593929cc6e3cf7c52c82eae135c3d7fd4a`, Mon 2026-10-26
14:00–16:00 UTC, BUY 0.09 units 1× limit IOC ≤ USD 50, 12 requests / 2 writes, close only the
lineage-verified position). It is a labelled **connectivity test**, not a strategy-generated
trade. Steps and GO/NO-GO: `docs/SD058_MONDAY_OWNER_RUNBOOK.md` (sign the intent, send the
`NAIVE_AS_UTC` acceptance and lock-lift approval, run, sign open and close). Nothing in SD-103
touched that intent, digest, operator, caps or transport. If today's window passes, a fresh
session-specific intent is prepared; nothing is rolled forward.
