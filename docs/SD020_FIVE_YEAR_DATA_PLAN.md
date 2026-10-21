# SD-020 five-year market-data plan

Status: `BLOCKED_OWNER` for authenticated retrieval; inventory and plan prepared
2026-10-21. No Alpaca request is authorized or performed by this document.

## Local inventory

The approved nested checkout was inspected read-only, including ignored local
data filenames and sanitized metadata. No SPY or QQQ historical bars were
found. No approximately five-year MSFT series was found.

Existing local evidence is limited to:

| Instrument | Source/feed | Coverage | Bars | Eligibility |
| --- | --- | ---: | ---: | --- |
| MSFT | Alpaca market-data API / SIP | 2026-07-29 to 2026-10-20 | 59 | Existing SD-004 evidence; insufficient for strategy acceptance |
| SOFI | Alpaca market-data API / IEX | 2024-01-02 to 2026-10-16 | 701 | Outside the requested universe; not consolidated SIP evidence |

The raw bundles and manifests remain ignored local files. They were not copied,
uploaded, or added to Git. No credentials, account identifiers, or account
responses were read.

## Dormant bounded retrieval scope

This is a plan for a future, separately approved read-only market-data action.
It is not permission to execute it.

- Endpoint: `GET https://data.alpaca.markets/v2/stocks/{ticker}/bars`
- Tickers: exactly `SPY`, `QQQ`, `MSFT`
- Window: `2021-10-21` through `2026-10-20`, UTC cutoff `2026-10-20`
- Contract: `timeframe=1Day`, `feed=sip`, `adjustment=split`, `currency=USD`,
  `sort=asc`, `limit=10000`
- Expected scale: approximately 1,250 regular sessions per instrument; the
  actual count must come from a verified exchange calendar, not estimation
- Maximum: one isolated persistent budget per ticker, 20 total HTTP requests
  including retries/pages, with no request outside this exact ticker/window
- Output: ignored local research-only JSON plus a sanitized SHA-256 manifest;
  never commit raw bars or credentials
- Explicit exclusions: account, portfolio, positions, orders, trading, eToro,
  paid feeds, model calls, and any symbol not listed above

Suggested commands after explicit approval, using only environment variable
names and never secret values:

```powershell
.\.venv\Scripts\python.exe -m sidedeck.application.p5_alpaca_history `
  --ticker SPY --start 2021-10-21 --end 2026-10-20 --cutoff-date 2026-10-20 `
  --feed sip --env-file .env --key-id-env <approved-key-id-name> `
  --secret-env <approved-secret-name> --budget-file data/sd020-spy-budget.json `
  --output data/sd020-spy-sip.json
```

The same command shape would be used separately for QQQ and MSFT with distinct
budget, output and manifest paths. A 401/403, entitlement failure, pagination
overrun, incomplete calendar, or unexpected source response stops that ticker;
it does not trigger retries outside the approved budget or a feed downgrade.

## Admission after retrieval

Each bundle must pass, independently and before strategy evaluation:

1. exact instrument identity, USD currency, regular daily session and SIP
   provenance;
2. unique chronological dates, valid OHLCV and verified exchange-session
   calendar coverage;
3. explicit split/dividend adjustment basis and corporate-action lineage;
4. point-in-time cutoff and no future/look-ahead records;
5. sanitized manifest with request count, statuses, date range, bar count and
   digest; and
6. enough observations for the existing 80/20 locked OOS, walk-forward,
   minimum-trade and five-year screening gates.

Only then may SD-014–SD-019 produce an acceptance report. Retrieval success is
not strategy acceptance, and any instrument failing a gate remains
`INSUFFICIENT_DATA` or `NOT_ASSESSED`.

