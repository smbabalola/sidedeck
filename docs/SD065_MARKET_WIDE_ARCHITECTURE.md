# SD-065…SD-075 — Market-wide scanning and multi-track trading architecture

**Owner directive:** 2026-10-22, "Market-wide autonomous scanning and multi-agent trading".
**Status:** offline packages SD-065…SD-068, SD-070, SD-071 IMPLEMENTED (fixture tests only).
No real scan coverage, market data, research run, order or broker request has occurred.
**Priority:** the SD-058 MSFT eToro Demo pilot remains the highest-priority execution milestone.
Nothing in this work changes its signed intent, digest, unlock, request budget or execution path.

## 1. Runtime principle

SideDeck's own deterministic code decides. ChatGPT, Codex and Claude are development tools and
are never part of the runtime loop. Research agents (TradingAgents, AI Hedge Fund/BuffettAgent,
day-trader methodologies re-implemented natively) produce `ResearchSignal` opinions only. An
agent can never grant itself execution permission (SD-070 rejects any payload containing
order/execution/permission/approval/size/broker/account fields).

## 2. Pipeline

```
Universe (SD-065) ─► Stage A broad scan (SD-067) ─► Stage B per-track shortlist (SD-067)
   ─► Stage C research on shortlist only (SD-069 adapters → SD-070 ResearchSignal)
   ─► Stage D decision engine (SD-071/072): ELIGIBLE | WATCHLIST | ABSTAIN | REJECTED
   ─► separately authorized eToro Demo execution service (SD-074; needs SD-063 + SD-064 + owner release)
```

| Stage | Module | Output | Never does |
|---|---|---|---|
| Universe | `sd065_market_universe.py` | point-in-time members + six eligibility flags | assume broker coverage; use today's list for history |
| A | `sd067_market_scanner.run_broad_scan` | `ScanFeatures`, exclusions, timing, coverage ratio | read bars after the cutoff; trim stale data silently |
| B | `sd067_market_scanner.build_shortlist` | ranked candidates + research subset | treat scores as expected returns |
| C | SD-069 (next) | `ResearchSignal` | carry order fields |
| D | `sd071_decision_engine.decide` | `Decision` with sizing (ELIGIBLE only) | grant execution (`NOT_GRANTED_BY_DECISION_ENGINE` is enforced) |

Design capacity targets (not current capability): 3,000–6,000 instruments, 100–300 quantitative
candidates, 10–30 research candidates per cycle, zero or more final proposals. Real throughput
must be measured on the owner's hardware and provider limits (`ScanReport.duration_seconds`,
`bars_read`, `coverage_ratio`).

## 3. Market Universe Manager (SD-065)

- Canonical id per security; dated `TickerInterval`s (symbol changes, ticker reuse after a gap);
  overlapping intervals or one ticker on two securities at once are refused.
- Listing/delisting dates, dated index membership, corporate actions, suspensions, data-source
  coverage with provenance, broker mappings (Demo/Paper only; Real refused) and exclusions.
- Separate flags: `LISTED_ACTIVE`, `MARKET_DATA_COVERAGE`, `SUFFICIENT_HISTORY`,
  `STRATEGY_ELIGIBLE`, `BROKER_MAPPED`, `BROKER_EXECUTION_ELIGIBLE`. Execution eligibility needs a
  *verified* mapping explicitly marked execution-eligible.
- Survivorship: `universe_as_of(D)` includes a security only if its listing interval is known to
  cover D. Symbol-directory snapshots are `SNAPSHOT` basis and are refused for any earlier date
  (`survivorship_risk=True` is reported).
- Versioning: SHA-256 digest of canonical JSON; tampered files fail to load; `refresh` produces
  version N+1, never drops a security (delist instead) and refuses silent history rewrites unless
  `allow_history_correction=True` is passed and the rewrite is reported.
- Markets: US phase 1 (discovery on); UK (FTSE 100/250, LSE), EU equities and major FX pairs are
  designed but discovery and execution are off. Cryptocurrencies are refused.
- Parser for Nasdaq Trader `nasdaqlisted.txt`/`otherlisted.txt` (test issues, warrants, rights,
  units, preferreds, deficient issuers and duplicates rejected with reasons). **Not yet run on a
  real file** (see SD-075A).

## 4. Data-source capability matrix (SD-066)

Encoded only from facts already recorded in repo docs. No source is real-time; IEX is never a
consolidated tape; unknown consolidation stays `None`. Only `APPROVED_PUBLIC` sources are usable
autonomously; `ProviderBudget` refuses a non-zero budget for any other source.

Current result: **SWING/POSITION daily** need → only owner-supplied CSV is autonomously usable;
Alpaca SIP is `AUTHORIZATION_EXHAUSTED`. **DAY 5-minute** need → `BLOCKED_EXTERNAL` (no approved
intraday consolidated source). DAY therefore stays research design only.

Budgets: reserve-before-send, persisted per provider (survives restart), per-window rate limit,
lifetime cap, clock-regression refusal, circuit breaker after N failures, retries only for
429/5xx up to the policy limit and never for 401/403/unknown outcomes.

## 5. Tracks and scheduling (SD-067/SD-068)

| Track | Horizon | Scan inputs | Default filters |
|---|---|---|---|
| DAY | same session | pre-open daily screen; 5-min watchlist (blocked: data) | price ≥ 5, $ADV ≥ 50 M, ATR ≥ 2 %, spread ≤ 10 bps **required** |
| SWING | 2–15 trading days | daily OHLCV | price ≥ 5, $ADV ≥ 20 M, ATR ≤ 8 %, no earnings within 5 days |
| POSITION | 15–180 trading days | daily + SEC fundamentals | price ≥ 10, $ADV ≥ 10 M, ≥ 252 sessions, above SMA200 |

Signals keep their own track, horizon, capital and exit rule. The decision engine ignores
signals from another track (`IGNORED_OTHER_TRACK`), so a POSITION thesis can never authorize a
DAY trade, and no position is converted between tracks.

Scheduler (`sd068_track_scheduler.py`): sessions computed in America/New_York and converted to
UTC (DST-safe; UK clock changes irrelevant), holidays from `us_equity_calendar`, explicit 1 p.m.
early closes, refusal outside verified calendar years. Default jobs: universe refresh and broad
scan pre-open, DAY scan every 5 minutes (open+5 → close−15), SWING three times, POSITION daily and
weekly (last session of the ISO week), risk monitor every minute, performance after close.
Broker reconciliation is **disabled** and never planned until an approved request budget exists.
Persistence: one running slot per job (leases), crash takeover after lease expiry, duplicates
refused, missed slots coalesced to the latest with older ones logged `SKIPPED_MISSED`. Track
controls accept only `RESEARCH_ONLY`/`SIMULATION_ONLY`.

## 6. Decision engine (SD-071/072)

Qualified signal = native strategy whose exact `(id, version)` is `ADMITTED` for the track;
admission requires locked OOS validation, ≥ 30 OOS trades and an evidence reference.
Agent-only agreement → `WATCHLIST` (`AGENT_AGREEMENT_IS_NOT_PROOF_OF_EDGE`); agent disagreement
→ `WATCHLIST`; conflicting qualified signals → `ABSTAIN`; short → `REJECTED` (long-only Demo desk).
Then: policy expiry and scope, market-data freshness, DAY session hours, duplicate holding,
position count, correlation, and sizing as the minimum of risk budget (risk % ÷ ATR stop), max
position, cash, gross exposure, cross-track instrument total and sector caps. Not broker
execution-eligible → `WATCHLIST`. `Decision.execution_permission` is fixed to
`NOT_GRANTED_BY_DECISION_ENGINE` and cannot be forged.

## 7. Path to autonomous Demo execution

Requires, in order: SD-058…SD-062 pilot completed and reconciled; SD-063 bounded autonomous
policy (strategies+versions, instruments/classes, exposure, loss, drawdown, position counts,
request budgets, sessions, expiry); SD-064 grant wiring with an off-host anchor; independent
review; and a distinct owner release. The four original eToro Demo positions remain immutable.
eToro Real and any real-money path remain permanently excluded.
