# SD-088 — UK equity integration and multi-exchange operations (2026-10-23)

**Owner directive (2026-10-23):** support UK equities and run a UK-market acceptance test this
morning without disturbing the US MSFT Demo pilot. Steering: `SIDEDECK_STEERING.md` §13. Work
packages SD-088…SD-096 in `TODO.md` (Milestone 4).

**Status in one line:** UK research engineering is implemented and tested offline; **no genuine
UK market data exists locally**, so genuine-data acceptance (G1) is `BLOCKED_OWNER` and the five
candidate names correctly **ABSTAIN**. The simulated trade and every negative scenario pass on a
clearly labelled synthetic fixture. No network request, credential, broker call or order occurred.

Two milestones, never confused:

| Milestone | Meaning | Status |
|---|---|---|
| UK research acceptance | correctly sourced UK instruments recognised and scanned on LSE hours, GBP/GBX normalised, horizon signals, auditable simulated trade | Engineering **IMPLEMENTED**; genuine-data part **BLOCKED_OWNER** (SD-094) |
| UK Demo execution acceptance | separately approved eToro Demo UK buy-and-close with broker evidence and reconciliation | **NOT STARTED — BLOCKED_OWNER** (SD-095) |

## 1. What was built

| ID | Module | What it does |
|---|---|---|
| SD-089 | `sd089_exchange_calendar.py` | `XNYS` and `XLON` calendars. XLON: Europe/London, continuous trading 08:00–16:30, half days close 12:30, England & Wales bank holidays 2022–2027 incl. exceptional closures (2022-06-03 Jubilee, 2022-09-19 State Funeral, 2023-05-08 Coronation, moved 2022 spring holiday). Uncovered years fail closed. |
| SD-090 | `sd090_uk_market.py`, `sd065_market_universe.py` | UK enabled for **discovery only** (execution never). Records carry optional `isin` (ISO 6166 check digit) and required-for-UK `quote_unit`. Unit labels case-sensitive: `GBp`/`GBX` = pence, `GBP` = pounds, `gbp`/`Gbp` refused. Exact `Decimal` /100 normalisation, 50× day-over-day jump = suspected unit flip (fail closed). LSE TIDMs (`BP.`, `BT.A`, `SHEL`); vendor forms (`BP.L`, `AZN.LON`, `BARC LN`, `LON:BP`) refused. Owner-file parsers for listings (ticker changes merged by ISIN) and FTSE 100/250 membership (snapshot rows never backdated). Investment trusts, preference shares, ETCs/ETNs, DRs etc. rejected; unknown types rejected, never guessed. |
| SD-091 | `sd068_track_scheduler.py` | Each job names its calendar. `xlon.*` jobs (UK universe refresh, broad scan, SWING review, POSITION daily/weekly; DAY and broker reconcile disabled). Non-US jobs must be namespaced, so US and UK slots never collide; per-exchange track controls; execution modes still refused. US behaviour unchanged (default `XNYS`). |
| SD-092 | `sd092_uk_scanner.py`, `sd066_data_capability.py`, `sd067_market_scanner.py` | UK scan: universe → eligibility → GBP normalisation → provenance/basis checks → XLON-calendar scan → DAY/SWING/POSITION rankings (GBP thresholds) → native SWING method signals → decision engine. One data basis per run (fixtures can never enter a REAL_DATA run). Cutoff must be a *completed* LSE session. DAY needs fresh normalised spreads. |
| SD-093 | `sd093_uk_sim_desk.py` | SIMULATION-only desk: append-only SQLite events (UPDATE/DELETE blocked by trigger), separate simulated venue table, idempotent intents, crash recovery by **lookup only**, unknown outcome → `UNRESOLVED` + kill-switch, protected-book refusal, reconciliation. UK stamp duty (0.5% on ordinary-share purchases) modelled as a simulation assumption and carried in the cost basis. |
| SD-096 | `sd096_uk_acceptance.py` | Acceptance runner: genuine-data inventory, fixture scan, simulated trade, scenario matrix. |

## 2. UK data sources (SD-092 capability matrix)

| Need | Source | Status | Why |
|---|---|---|---|
| Listings, ISIN, quote unit | `OWNER_CSV_IMPORT_UK` (`sidedeck.uk_listings.v1` + `.licence.txt`) | usable, **none supplied** | owner declares licence per file |
| FTSE 100/250 constituents | `FTSE_RUSSELL_CONSTITUENTS` | NOT_APPROVED | licensed index data; redistribution restricted |
| | `LSE_WEBSITE` | NOT_APPROVED | site terms restrict automated reuse |
| Daily OHLCV | `OWNER_CSV_IMPORT_UK` | usable, **none supplied** | |
| | `ETORO_DEMO_MARKET_DATA_UK` | OWNER_AUTHORIZATION_PER_RUN | UK coverage/candle entitlement unverified |
| | `STOOQ_UNOFFICIAL_UK`, `YAHOO_UNOFFICIAL_UK` | NOT_APPROVED | terms/redistribution unclear (not assumed free) |
| Intraday quotes/spreads | none | **BLOCKED_EXTERNAL** → UK DAY abstains | |
| Corporate actions | none approved | BLOCKED_EXTERNAL | |
| Exchange calendar | transcribed table, rule-cross-checked | TRANSCRIBED_RULE_CROSSCHECKED | `GOV_UK_BANK_HOLIDAYS` (OGL v3.0) PENDING_POLICY_REVIEW |
| Currency/unit metadata | from the listing file per instrument | none supplied | |

## 3. SD-094 — bounded data request (prepared, NOT executed)

Nothing below has been run. Each part needs the owner's explicit approval (preferably as an
SD-077 signed `DataAuthorization`); any part may be approved independently.

| Part | Exact request | Count | Auth | Purpose |
|---|---|---|---|---|
| A | `GET https://www.gov.uk/bank-holidays.json` | 1, no retry, no redirect | none (public, OGL v3.0) | corroborate XLON closures for published years; LSE half days still need the owner to confirm the LSE business-days notice manually |
| B | `GET /api/v1/market-data/search?internalSymbolFull=<symbol>` for the five candidate LSE lines (owner confirms eToro's exact symbol spelling, e.g. `BP.L`, before the run) | ≤ 5, stop on first non-200, 0 retries | eToro Demo key, read-only | resolve eToro instrument IDs; verify exchange, currency/unit (GBX vs GBP), instrument type, tradability |
| C | `GET /api/v1/market-data/instruments/{instrumentId}/history/candles/{direction}/{interval}/{candlesCount}` for each ID resolved in B, daily interval as documented in the eToro API portal, ≤ 300 candles | ≤ 5, 0 retries | same | daily OHLCV with provenance for the UK scan |

Constraints: B+C ≤ 10 authenticated GETs on a **new, separate** budget ledger; never the MSFT
pilot's request budget, digest or unlock; run only **after** today's MSFT window closes (after
15:30 UTC); raw responses in ignored `data/uk/`; no account, portfolio or order endpoint.
Alternative without any request: the owner supplies licensed files in `data/uk/`
(`uk_listings*.csv` + `*.licence.txt`, bars under `data/uk/bars/`).

## 4. SD-095 — what an actual eToro Demo UK order would still need

| Requirement | Status |
|---|---|
| eToro Demo instrument ID for the chosen LSE line | MISSING (SD-094 B) |
| UK stock identity and currency/unit as eToro reports it | MISSING |
| Fractional-share and minimum-order eligibility for that instrument | MISSING — MSFT rules are **not** assumed |
| Fresh executable reference price (≤ 60 s) during LSE hours | MISSING |
| Broker request allowlist for UK endpoints | NOT WRITTEN |
| Separate signed owner pilot intent (new digest; not SD-053) | NOT CREATED |
| Separate owner authorisation for authenticated access and execution | NOT GRANTED |
| Independent security review and release approval | NOT DONE |

The current broker transport stays locked for UK; `UNLOCKED_PILOT_DIGEST` admits only the
signed MSFT digest. The MSFT authorisation is valid only for MSFT under its existing scope.

## 5. Morning acceptance run (2026-10-23)

`python -m sidedeck.application.sd096_uk_acceptance` (simulated clock: cutoff Thu 2026-10-22,
scan 06:30 UTC, trade 08:00 UTC = 09:00 BST, exit 13:00 UTC):

- **Genuine data:** `NO_GENUINE_UK_DATA`. BP, Shell, HSBC, AstraZeneca, Unilever →
  `ABSTAIN` (`NO_SOURCED_RECORD`, `NO_APPROVED_MARKET_DATA`). Their TIDMs/ISINs are recalled
  reference values marked `UNVERIFIED_PENDING_SOURCE`.
- **Fixture scan (SYNTHETIC_FIXTURE, `ZZ…` ISINs):** universe 12; 9 scanned; excluded:
  ambiguous unit `gbp`, suspected unit flip, stale series; listing rejections: investment trust,
  vendor symbol `SYV.L`, unknown type. DAY 0 candidates (no spreads); SWING 8 and POSITION 4
  ranked; decisions SWING 3 WATCHLIST / 5 ABSTAIN, POSITION 4 ABSTAIN; **0 ELIGIBLE** (no
  admitted strategy) → acceptance `ABSTAIN_NO_GENUINE_DATA_FIXTURE_RUN`.
- **SIMULATION trade:** controlled execution fixture (labelled; not from a research signal):
  BUY 17 × £8.69 (869.0p source ask) + £0.74 stamp duty → position → SELL 17 →
  reconciliation `MATCHED`, flat, realised P&L = cash change.
- **Scenarios:** stale quote, missing mapping, market closed (weekend and after 16:30 BST),
  minimum order, ambiguous unit, partial fill (4/10), duplicate (1 fill), interrupted execution
  (recovered by lookup, 1 submission), unknown exit (UNRESOLVED + kill-switch, position
  "may be open"), protected portfolio separation — all refused or resolved as required.

These are plumbing results on synthetic data: not market coverage, signals or performance.
