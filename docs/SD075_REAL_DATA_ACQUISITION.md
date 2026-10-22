# SD-075 — First genuine market-data acquisition (owner-gated)

**Status (2026-10-22):** importers and runners are built and tested offline with mock transports.
**No request has been made.** Both acquisitions need an owner-signed SD-077 data authorization.
The MSFT Demo pilot (SD-053/SD-057/SD-058) is unaffected: different code, namespace and window.

## Authorization mechanism (SD-077)

The owner signs a `DataAuthorization` digest with the existing approval key in the dedicated SSH
namespace `sidedeck-data-authorization` (not the pilot or paper-approval namespaces). The record
pins provider, exact URLs, maximum requests, maximum retries, expiry (≤ 7 days) and an explicit
`owner_terms_reviewed: true`. SideDeck verifies with `ssh-keygen -Y verify` against
`data/approval_allowed_signers` and reserves each request in a persistent ledger **before** it is
sent. Broker, account and order paths cannot be authorized. A chat message or CLI flag is not an
authorization.

## SD-075A — Nasdaq Trader symbol directories

| Item | Value |
|---|---|
| URLs | `https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt`, `.../otherlisted.txt` |
| Requests | exactly 2, retries 0, no redirects, no credentials or cookies, ≤ 5 MB each |
| Output (ignored `data/universe/`) | raw files + SHA-256, SNAPSHOT-basis registry JSON, sanitized summary |
| Committable | sanitized counts only (by exchange, asset type, rejection reason) |
| Meaning | **current** listings only: not point-in-time membership, tradability or price coverage |
| Owner check | read the Nasdaq Trader terms/usage notice for the Symbol Directory before signing |

Owner steps (PowerShell, from the nested `sidedeck` folder; steps 1–2 make no network request):

```powershell
# 1. Draft a 24-hour authorization and prepare its digest
.venv\Scripts\python.exe -m sidedeck.application.sd075a_nasdaq_universe_import draft --out data\sd075a-draft.json
.venv\Scripts\python.exe -m sidedeck.application.sd077_data_authorization data\sd075a-draft.json
# 2. Run the printed OWNER_SIGNING_COMMAND (re-checks the digest, then ssh-keygen -Y sign)
# 3. Import: exactly two GETs
.venv\Scripts\python.exe -m sidedeck.application.sd075a_nasdaq_universe_import run `
  --authorization data\authorizations\<id>.json `
  --signature data\authorizations\<id>.digest.payload.sig
```

## SD-075B — Alpaca SIP daily-bar pilot (proposal for owner approval)

`python -m sidedeck.application.sd078_alpaca_sip_pilot proposal` prints this scope.

| Item | Value |
|---|---|
| Endpoint | `GET https://data.alpaca.markets/v2/stocks/{symbol}/bars?timeframe=1Day&feed=sip&adjustment=split&limit=10000` (market data only; never a trading host) |
| Entitlement | SIP historical bars returned HTTP 200 in SD-021 (2026-10-21); current entitlement unverified until the run |
| Instruments (20) | SPY, QQQ, IWM, DIA, AAPL, MSFT, NVDA, AMZN, GOOGL, META, JPM, BAC, XOM, CVX, JNJ, UNH, PG, KO, HD, WMT |
| Period | 2022-01-03 → 2026-10-21 (1,205 regular sessions; inside the verified calendar years) |
| Granularity | 1Day regular-session bars, split-adjusted |
| Estimated records / storage | 24,100 bars / ≈ 4 MB JSON in ignored `data/sd075b/` |
| Max authenticated requests | **24** (20 first pages + 4 pagination contingency), **0 retries** |
| Pagination | limit 10,000 per page → one page per symbol expected; repeated/invalid cursor aborts |
| Failure policy | first failure (e.g. 401/403/429/5xx, schema error) stops the run; nothing is retried |
| Pacing / completion | sequential with 0.5 s spacing; under 2 minutes |
| Credentials | read from `.env` only after the signature verifies; never logged or written |
| Output | per-symbol raw JSON + SHA-256 manifest; SD-080 coverage report (COVERED / PARTIALLY_COVERED / UNAVAILABLE); SPY benchmark gate |

Owner steps mirror SD-075A, using `sd078_alpaca_sip_pilot draft --out …` and
`sd078_alpaca_sip_pilot run --authorization … --signature …`.

**Limitations:** split-adjusted only (no dividends/total return); SIP per provider, independent
corroboration still required for G1; the symbol set is chosen today, so survivorship bias applies to
this pilot; no intraday, quotes or spreads (DAY remains research-only). The exhausted SD-021
authorization and its budget files are never reused; this pilot has its own digest and ledger.

## After acquisition

1. Commit only sanitized summaries (counts, hashes, coverage) and update TODO with evidence.
2. Re-run SD-022/SD-023-style independent checks on SPY/QQQ/MSFT overlap with the SD-021 bundles.
3. Run the SD-067 scanner on the genuine pilot set and record real timing and coverage.
4. Keep acceptance at `RESEARCH_DATA_ONLY` until independent corroboration (G1) passes.
