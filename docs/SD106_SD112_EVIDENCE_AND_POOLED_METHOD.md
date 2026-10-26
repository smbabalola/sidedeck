# SD-106 genuine-evidence acquisition and SD-112 pooled admission method (2026-10-26)

Owner direction: improve genuine strategy evidence (20 instruments) and design a rigorous,
independently reviewed pooled OOS method **without** changing the production admission gate
or admitting anything automatically. Steering §16; TODO Milestone 5.

## 1. SD-106 — the 20-instrument Alpaca SIP data authorization (ready for the owner)

**Nothing has been requested.** The runner (`sd078_alpaca_sip_pilot`) is dormant until the
owner signs the exact SD-077 `DataAuthorization`.

| Item | Value (verified in code and tests) |
|---|---|
| Provider / host | `ALPACA_SIP_DAILY`, `data.alpaca.markets` only (market data; never a trading endpoint) |
| Endpoint | `GET /v2/stocks/{symbol}/bars?timeframe=1Day&feed=sip&adjustment=split&limit=10000` |
| Instruments (20) | SPY QQQ IWM DIA · AAPL MSFT NVDA AMZN GOOGL META · JPM BAC · XOM CVX · JNJ UNH · PG KO · HD WMT |
| Period | 2022-01-03 .. **2026-10-23** (last completed session before this draft; was 10-21) |
| Requests | **≤ 24** (20 first pages + 4 contingency), **0 retries**, stop at the first failure, every attempt reserved in a persistent ledger before sending |
| Expiry | 48 hours from the draft (SD-077 maximum 7 days) |
| Single use | `.consumed` marker + fixed ledger; a signed authorization can never be re-run |
| Signing | owner SSH key, namespace `sidedeck-data-authorization`, **pinned owner key** checked before verification (added today) |
| Credentials | read only after the signature verifies and **before** the single-use claim (fixed today: a misnamed variable no longer burns the authorization). Variable names must be passed explicitly; pair A (`ALPACA_API_KEY` / `ALPACA_API_SECRET`) is the only pair with verified access (SD-035: A HTTP 200, B HTTP 401) |
| Entitlement | SIP historical bars returned HTTP 200 in SD-021 (2026-10-21); current entitlement is unverified until the run |
| Licence / use | **Owner confirms** Alpaca's market-data terms permit this personal research use; SideDeck no longer asserts it (`--owner-confirms-terms-reviewed` is the owner's own flag) |
| Limitations | split-adjusted only (no dividends/total return); survivorship bias (today's large caps); no intraday/quotes; SIP per provider, independent corroboration still required |

**Owner steps (PowerShell, from `C:\Users\smbab\OneDrive\Documents\Projects\sidedeck\sidedeck`):**

```powershell
# 1. Draft (you confirm the terms review yourself with the flag)
.\.venv\Scripts\python.exe -m sidedeck.application.sd078_alpaca_sip_pilot draft --out data\authorizations\sd075b-draft.json --owner-confirms-terms-reviewed
# 2. Prepare: prints the digest and a digest-checked signing command (signs nothing)
.\.venv\Scripts\python.exe -m sidedeck.application.sd077_data_authorization data\authorizations\sd075b-draft.json --out-dir data\authorizations
# 3. Paste the printed OWNER_SIGNING_COMMAND, enter your key passphrase
# 4. Run within 48 h (exact file names are printed in steps 1-3; date = draft date)
.\.venv\Scripts\python.exe -m sidedeck.application.sd078_alpaca_sip_pilot run --authorization data\authorizations\sd075b-alpaca-sip-pilot-YYYYMMDD.json --signature data\authorizations\sd075b-alpaca-sip-pilot-YYYYMMDD.digest.payload.sig --key-id-env ALPACA_API_KEY --secret-env ALPACA_API_SECRET
```

**After retrieval (offline, READY once data exists):** coverage report (SD-080) is produced
by the run; then convert the raw files to admitted bundles, cross-check SPY/QQQ/MSFT against
the SD-021 bundles on overlapping sessions, flag splits/consolidations, rerun SD-103 and
SD-112, and report results by instrument, strategy and locked OOS period.

## 2. SD-112 — pooled OOS admission method (proposal only)

`python -m sidedeck.application.sd112_pooled_admission` → `data/sd112/pooled-proposal.json`.
The production gate is unchanged; verdicts are `PROPOSED_FOR_OWNER_REVIEW`,
`INSUFFICIENT_EVIDENCE` or `REJECTED`, never `ADMITTED`.

| Concern | How the method handles it |
|---|---|
| Same strategy, pre-specified rules | one fixed catalogue version; criteria constants fixed in code before results |
| Chronology | shared splits on the sessions common to all instruments before the holdout: 60 % TRAIN (not used to fit) / 40 % pooled OOS |
| Untouched holdout | **calendar-pinned**: every session from **2026-10-26** on. All bars up to 2026-10-23 were already examined (SD-021/SD-022), so only future bars are genuinely untouched; the holdout accrues as authorized fresh data arrives. Sealed by a commitment to the cut-off + strategy version (a data refresh cannot re-arm it); owner unseals once, only with ≥ 40 sessions, against a pre-declared pass rule (PF ≥ 1, mean trade return > 0). Trades crossing a segment boundary are excluded |
| Overlapping positions | trades whose holding periods overlap (any instrument) form one cluster |
| Correlated instruments | design effect n / (1 + (k−1)·ρ̄) from instruments' daily strategy returns; effective sample = min(clusters, design effect) ≥ 30 |
| Uncertainty / multiple testing | cluster block bootstrap (2,000, seeded); lower bound at a Bonferroni-adjusted one-sided 5 % / (3 strategies × 2 looks at these data) |
| Concentration | best instrument's share of net profit ≤ 50 %; top-10 % trades' share reported |
| Regimes | benchmark above/below 50-session SMA at entry; each regime needs ≥ 5 trades (else `REGIME_NOT_COVERED` → insufficient) and PF ≥ 0.8; a missing benchmark is insufficient evidence |
| Costs | 10 bps per side; must stay above PF 1 at 2× costs |
| Benchmark | equal-weight price-only buy-and-hold over the OOS window, reported next to the strategy's own compounded OOS return and exposure; **context only, not a criterion** (long/flat strategies with partial exposure are not like-for-like with buy-and-hold) |
| Bad instruments | all instruments pooled (no cherry-picking); instruments losing on their own are listed `EXCLUDED_LOSES_ON_ITS_OWN` and stay visible |

**Genuine results on the 3 available instruments (SPY, QQQ, MSFT), OOS 2024-10-18 → 2026-10-20:**
nothing is proposed.

| Strategy | Verdict | OOS trades | Effective sample | Pooled PF | Bootstrap lower PF | PF at 2× costs | Strategy / buy-and-hold return (exposure) |
|---|---|---:|---:|---:|---:|---:|---|
| channel mean reversion | **REJECTED** | 76 | 39.1 | 1.15 | 0.56 | 0.92 | +7.9 % / +34.6 % (9.5 %) |
| liquidity sweep reversal | INSUFFICIENT_EVIDENCE | 20 | 14.0 | 3.53 | 0.31 | 2.64 | +7.8 % / +34.6 % (1.3 %) |
| moving-average trend | INSUFFICIENT_EVIDENCE | 23 | 11.0 | 1.51 | 0.07 | 1.41 | +9.6 % / +34.6 % (50.7 %) |

Channel mean reversion per instrument: MSFT 31 trades PF 1.27; SPY 23 PF 1.24; QQQ 22 PF 0.93
(excluded on its own). It is the only strategy with enough effective evidence, and it fails on
uncertainty (lower bound 0.56), 2× costs and concentration. Its per-instrument picture also
changes with the OOS window (SD-021 80/20: SPY/QQQ strong, MSFT failed), which is itself a
sign of instability. Moving-average trend had a single down-trend trade, so that regime is
not covered.

**Independent review (2026-10-26):** 0 critical / 0 high / 5 medium / 6 low; all medium and
the material low items fixed with tests (calendar-pinned holdout and disclosed prior looks;
regime coverage; strategy return beside the benchmark; SD-078 run-path tests; read-only
history endpoint; crash-safe scheduler finish; scope checks before the single-use claim;
accurate boundary-exclusion count; correlation-evidence flag).

**Owner decisions needed before any use:** accept or amend the method and its criteria;
only after SD-106 data and a passing pooled OOS would the sealed holdout be unsealed once;
a production gate change would be a separate reviewed commit.
