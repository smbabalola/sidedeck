# M2 BuffettAgent version and SEC data compatibility — 2026-10-20

Status: version blocker **resolved**; Financial Datasets dependency **removed
for local SEC input**; SOFI data coverage **insufficient**. M2 real research
remains `NO-GO`. No LLM, Financial Datasets, SEC, eToro, Saxo or Alpaca
request was made.

## 1. Upstream version identity (resolved)

The installed upstream distribution is named `aihf` (not `ai-hedge-fund`), so
the previous bridge lookup always failed. It is an editable install of a git
checkout, so the version number alone does not pin the code.

`sidedeck.bridges.upstream_identity` now resolves:

| Install type | Identity | Rule |
|---|---|---|
| Editable git checkout | `aihf==<version>+git.<40-hex commit>` | `git rev-parse HEAD`; refuses tracked uncommitted changes |
| VCS wheel (`direct_url.json` `vcs_info`) | `aihf==<version>+git.<commit>` | recorded commit, no git call |
| Index release (no `direct_url.json`) | `aihf==<version>` | version only |
| Local directory without revision, or missing distribution | — | fails closed |

Local result: `aihf==2.5.0+git.ec025370c66cf71d3ea2f2d8f463b5934c1c48af`
(`VERIFIED`, clean checkout, origin `virattt/ai-hedge-fund`). The bridge now
stamps this identity as `upstream_version`.

```powershell
$env:PYTHONPATH = (Resolve-Path ".\src").Path
& "..\ai-hedge-fund\.venv\Scripts\python.exe" -m sidedeck.bridges.upstream_identity
```

## 2. What BuffettAgent actually reads (verified from source at `ec02537`)

`BuffettAgent` is a system prompt on `LLMAgent`. For a **daily** cutoff,
`predict()` calls only `build_snapshot()`, which uses exactly two data-client
methods:

- `get_financial_metrics(ticker, as_of[:10], period="ttm", limit=20)`; at
  least 4 rows are required, otherwise it abstains.
- `get_company_facts(ticker)`: sector and industry only, optional.

Intraday cutoffs additionally call price/news methods and are out of scope.
`FDClient` is used only if no data client is injected. **With
`--fundamentals-json`, Financial Datasets is not required.** The preflight now
reports `fundamentals_source=LOCAL_SEC_FILE`, `fundamentals_credential=NOT_REQUIRED`
in that mode.

The prompt uses 12 per-period fields, all optional: `market_cap`, `price_to_earnings_ratio`,
`return_on_equity`, `gross_margin`, `operating_margin`, `net_margin`,
`debt_to_equity`, `current_ratio`, `revenue_growth`, `earnings_per_share`,
`book_value_per_share`, `free_cash_flow_per_share`. Missing values are shown as
`-`. The persona is told to go neutral when data are insufficient, so a sparse
snapshot would produce an uninformative call, not an error.

## 3. SOFI coverage (`data/sofi-buffett-roe-eps-v2.json`, as of 2026-10-19)

| Field | Periods populated (of 20) | In newest period |
|---|---|---|
| return_on_equity | 20 | yes |
| earnings_per_share | 5 (annual only) | no |
| all other 10 fields | 0 | no |

Buffett checklist: moat `PARTIAL` (ROE only); management, financial strength
and valuation `NO_EVIDENCE`. Coverage gate: **FAIL**.

SEC concepts present locally for the gaps (counts only, **not validated**):

| Field | Candidate concepts (observations) | Note |
|---|---|---|
| net_margin / revenue_growth | NetIncomeLoss (78), RevenuesNetOfInterestExpense (69) | bank revenue definition needs owner sign-off |
| debt_to_equity | DebtLongtermAndShorttermCombinedAmount (42), StockholdersEquity (115) | excludes deposits; must not relabel total liabilities as debt |
| book_value_per_share | StockholdersEquity (115), CommonStockSharesOutstanding (42) | existing BVPS audit work is not yet merged into the input |
| free_cash_flow_per_share | NetCashProvidedByUsedInOperatingActivities (51), PaymentsToAcquireProductiveAssets (47) | YTD durations need TTM normalisation |
| market_cap, P/E | shares (22/42), diluted EPS (69) | need validated filing-date price; see `P5_VALUATION_EVIDENCE.md` |
| operating_margin | OperatingIncomeLoss (3) | effectively unavailable |
| current_ratio | AssetsCurrent (4), LiabilitiesCurrent (5) | unclassified bank balance sheet; leave empty |
| gross_margin | CostOfRevenue (59) | not meaningful for a bank presentation without a definition decision |

## 4. Cost of the bounded run

Exact upstream prompt rendered offline: 1,628 system + 1,989 user characters,
about **905 input tokens** (estimated as characters ÷ 4; not a tokenizer count).
One snapshot means **one LLM call**, and repeats are served from upstream's
prompt cache. Upstream `make_llm` caps output at 4,096 tokens for Anthropic.
OpenAI and Google have no cap, so their worst case is unbounded until a cap is
added. The dollar bound is computed only from operator-supplied prices:

```powershell
$env:PYTHONPATH = (Resolve-Path ".\src").Path
& "..\ai-hedge-fund\.venv\Scripts\python.exe" -m sidedeck.application.p5_buffett_coverage `
  --fundamentals-json data/sofi-buffett-roe-eps-v2.json --ticker SOFI --as-of 2026-10-19 `
  --companyfacts data/sofi-companyfacts-raw.json --provider anthropic `
  --input-usd-per-mtok <price> --output-usd-per-mtok <price> --output data/<new-file>.json
```

## Next actions

Superseded by the bank-aware reconstruction in `M2_SOFI_BANK_METRICS.md`,
which also lists the owner decisions now blocking the gate. Request owner
authorisation for exactly one BuffettAgent call only after the gate passes,
with the chosen model, prices and cost bound stated.
