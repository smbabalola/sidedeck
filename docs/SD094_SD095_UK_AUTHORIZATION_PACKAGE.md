# SD-094 / SD-095 — UK data requests and BP Demo pilot: authorization package

**Status:** prepared, **nothing authorized or executed**. This document is the single place the
owner reviews before signing. Each part is a separate, independently bounded authorization; none
implies another, none uses the SD-053/SD-057/SD-058 MSFT pilot's intent, digest-specific unlock,
request ledger or window, and none permits eToro Real (permanently excluded).

## What is complete without any authorization (offline, verified in tests)

- SD-098 importer for owner-supplied licensed files (`data/uk/manifest.json`): ISIN/TIDM identity,
  GBX/GBp/GBP units, daily OHLCV, SHA-256 per file, provenance and retrieval time, licence and
  source statements, corporate actions (splits/consolidations back-adjust RAW prices; dividends
  recorded price-only), refusal of contradictory, unsafe, synthetic-in-real or future-dated input.
  Stale or session-incomplete series are excluded by the scanner, never repaired.
- SD-096/SD-092 REAL_DATA scan on imported data; SD-097 read-only UK dashboard with REAL DATA /
  SIMULATION / SYNTHETIC FIXTURE / NO DATA labels.
- SD-094 part A runner (single GET, verifier, ledger) and B/C templates — none executed.

**Fastest unblocking route that needs no request at all:** the owner places licensed files under
`data/uk/` with a `manifest.json` (schema in `src/sidedeck/application/sd098_uk_import.py`). The
scanner then runs on genuine evidence on the next refresh.

## SD-094A — UK calendar corroboration (public, unauthenticated)

| Item | Value |
|---|---|
| Endpoint | `GET https://www.gov.uk/bank-holidays.json` (Open Government Licence v3.0) |
| Requests | exactly 1; 0 retries; no redirects; no credentials or cookies; 2 MB cap |
| Evidence | raw bytes + SHA-256 in `data/uk-calendar/raw/<authorization_id>/`; ledger entry |
| Authorization | SD-077 `DataAuthorization` for provider `GOV_UK_BANK_HOLIDAYS`, signed in namespace `sidedeck-data-authorization` |
| Commands | `python -m sidedeck.application.sd094_uk_data_requests prepare-a` → owner signs the printed digest → `... run-a --authorization <file> --signature <file>` |
| Limits | corroborates England & Wales bank holidays only; LSE half days (incl. the four rule-only half days) still need an LSE business-days notice |

## SD-094B — UK instrument discovery (authenticated eToro Demo, read-only)

| Item | Value |
|---|---|
| Endpoint | `GET /api/v1/market-data/search?internalSymbolFull=<symbol>` (same path family as the SD-050/SD-052 MSFT lookup) |
| Instruments | at most 5: BP (`BP.`), Shell (`SHEL`), HSBC (`HSBA`), AstraZeneca (`AZN`), Unilever (`ULVR`); owner confirms eToro's exact symbol spelling first |
| Requests | ≤ 5, 0 retries, stop on the first non-200; new budget ledger |
| Credentials | the eToro Demo pair, read-only market data only; never account, portfolio or order routes |
| Accept | for each line: instrument ID, exchange = LSE, instrument type, quote currency and unit (GBX/GBP), tradability/fractional flags as reported — all recorded **as reported**, not inferred |
| Authorization | a separate owner-signed one-shot launcher (SD-052 pattern), run after the MSFT pilot window closes |

## SD-094C — UK daily history (authenticated eToro Demo, read-only)

| Item | Value |
|---|---|
| Endpoint | `GET /api/v1/market-data/instruments/{instrumentId}/history/candles/{direction}/{interval}/{candlesCount}` |
| Instruments | only IDs verified in B; ≤ 5 requests (one per instrument), ≤ 300 daily candles each, 0 retries |
| Expected format | daily OHLC(V) with timestamps; the import path stores raw bytes + SHA-256 and maps into SD-098 series with an explicit unit |
| Precondition | documented confirmation that this endpoint supplies daily LSE history and that research use is permitted (entitlement is `NOT_VERIFIED` in `docs/M2_ETORO_MARKET_DATA_ENDPOINT_MATRIX.md`); B completed |
| Authorization | separate owner-signed authorization and new budget ledger |

## SD-095 — first UK eToro Demo pilot proposal: BP ordinary shares

**Candidate:** BP p.l.c., TIDM `BP.`, expected ISIN `GB0007980591` (**unverified until sourced**).
No UK order is authorized by this document.

| Requirement | Status / how it is satisfied |
|---|---|
| Exact eToro instrument ID | **Unknown** — from SD-094B only; never guessed |
| Ordinary equity vs CFD | Must be shown by eToro's reported instrument type and a long, 1× (non-leveraged) open; refuse if the instrument or the eligibility response indicates a CFD-only line |
| GBP/GBX normalisation | eToro's reported quote unit recorded from B; SideDeck normalises to GBP with exact Decimal (`sd090_uk_market`); unit flips refused |
| Broker currency, minimum order, fractional rules | From the read-only eligibility call at preflight (`POST /api/v2/trading/info/demo/eligibility`); refuse on any mismatch |
| Fresh price and sizing | `GET /api/v2/market-data/rates?instrumentIds=<id>` ≤ 60 s old; units from the signed notional cap; limit = min(signed max, fresh ask × 1.005) |
| Virtual-capital cap | proposed ≤ USD 50 equivalent (owner sets the exact figure in the signed intent) |
| Separate approvals | (1) signed UK pilot intent (new digest, `sidedeck-etoro-pilot-release`); (2) per-order open and close approvals (`sidedeck-etoro-pilot-approval`); (3) a UK-specific execution release; the MSFT unlock never covers a UK digest |
| Protected baseline | preflight reconcile (`GET /api/v1/trading/info/demo/pnl`); the four original positions are never closable; instrument must not be in the baseline |
| Endpoints (allowlist) | pnl (GET), eligibility (POST, read-only), rates (GET), open `POST /api/v2/trading/execution/demo/orders`, lookup `GET /api/v2/trading/info/demo/orders:lookup`, close `POST /api/v1/trading/execution/demo/market-close-orders/positions/{positionId}`, close info `GET /api/v1/trading/info/demo/close-orders/{orderId}` |
| Request budget | ≤ 12 requests, ≤ 2 writes, 0 write retries (same shape as SD-053): pnl ≤ 2, eligibility 1, rates 1, open 1, lookup ≤ 3, close 1, close-info ≤ 3 |
| Window | an LSE session (08:00–16:30 London), not a half day, with ≥ 20 minutes left at open; never rolled forward |
| Lifecycle | open once → lookup-only recovery (referenceId → orderId → positionId) → separately signed close → close-info → final reconcile; COMPLETE only on close FILLED + reconcile MATCHED + 0 SideDeck positions; anything else UNRESOLVED + kill-switch |
| Review | independent security review of the UK intent, unlock and runbook before release (the SD-056 review covers the transport, not UK scope) |

**Blockers (owner):** sign SD-094B (identity) → optionally SD-094C or supply licensed files →
review this proposal → sign the UK intent and a UK execution release. Until then UK broker
execution stays disabled and the transport stays locked for UK.
