# M2 MSFT SEC financial reconstruction

Status: offline evidence only; BuffettAgent execution remains blocked.

`p5_sec_msft_metrics` reconstructs MSFT from the owner-supplied
`data/msft-companyfacts-raw.json` without another download. It keeps the
earliest eligible filing for each period, rejects future filings, preserves
accession IDs, filing dates, XBRL units and SEC archive provenance, and checks
TTM values against four filing-period quarters. It is an industrial-company
profile and does not use the bank-specific definitions.

Command used locally:

```powershell
.venv\Scripts\python.exe -m sidedeck.application.p5_sec_msft_metrics `
  --companyfacts data/msft-companyfacts-raw.json --as-of 2026-10-20 `
  --output $env:TEMP\msft-buffett-v1.json --audit-output $env:TEMP\msft-audit-v1.json
```

## Results

The latest eligible period is 2026-06-30, filed 2026-07-29. Ten of twelve
BuffettAgent candidate metrics are validated in that period:

- validated: net margin, gross margin, operating margin, revenue growth, ROE,
  current ratio, debt/equity, diluted EPS, FCF/share and BVPS;
- unavailable: market cap and P/E, because no independently validated
  historical price and matching share-basis evidence is present.

There are 8 historical periods with all ten non-valuation metrics validated,
and 70 periods with at least one validated metric in the audit. Every exported
metric remains filing-dated; missing capex, ambiguous
shares, future filings and failed quarter reconciliation are excluded rather
than converted to zero or carried forward. EPS allows only a documented
two-cent rounded-fact tolerance. FCF/share uses annual weighted diluted shares
with Q1-Q3 supporting observations; it does not sum share counts.

The general-sector Buffett coverage gate is **FAIL**: 10/12 latest fields,
with valuation showing `NO_EVIDENCE`. The generated dataset is structurally
compatible with the local `LocalFiledDataClient`, but it is not research
approval and no model call was made. MSFT is the stronger offline candidate,
not a genuine BuffettAgent result.

## Remaining requirements

Historical prices, price adjustment basis, market-cap share basis and P/E still
require independent point-in-time validation. A real research run additionally
requires explicit provider authorization and bounded spend. Broker execution,
automatic allocation, eToro, Saxo and Alpaca remain disabled.
