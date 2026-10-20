# M2 SOFI bank-aware metrics and valuation evidence — 2026-10-20

Status: offline reconstruction complete; coverage gate still **FAIL** on
relevant evidence. M2 real research remains `NO-GO`. No LLM, Financial
Datasets, SEC, eToro, Saxo or Alpaca request was made; upstream BuffettAgent
is unmodified. All inputs are the existing local files in `data/` (gitignored).

## What was built

| Module | Purpose |
|---|---|
| `p5_sec_bank_metrics` | TTM net margin, revenue growth, borrowings-based debt/equity and FCF from SEC Company Facts, with per-period lineage and availability dates. Extends the existing ROE/EPS input. |
| `p5_buffett_coverage --sector-profile bank` | Gate judged on relevant fields only; populating a not-applicable field fails the gate. |
| `p5_market_cap_evidence` | Market-cap candidates: cover-page shares × first close **after** the filing date. Audit only. |
| `p5_valuation_evidence.load_price_bars` | Shared price-file validation (refactor, behaviour unchanged). |

### Reconciliation rule

TTM = FY + current YTD − prior-year YTD, using the earliest filing for each period
(existing converter). It is checked against the sum of four quarters that use
**separately tagged 3-month facts** where filed, with tolerance 0.1%. Re-deriving
quarters from the same YTD facts would be circular, so:

- `RECONCILED`: the sum matches and at least one quarter is an independent 3-month fact.
- `ARITHMETIC_ONLY`: no independent quarters (e.g. cash flow, which 10-Qs report YTD only).
- `MISMATCH`: a 3-month fact conflicts with the YTD difference, or the sum is off.

Only metrics whose every TTM input is `RECONCILED` enter the Buffett input.

## Field decisions for SOFI (US bank holding company)

| Field | Decision | Definition / reason |
|---|---|---|
| net_margin | **Included** (17 of 20 periods) | TTM NetIncomeLoss / TTM RevenuesNetOfInterestExpense (total net revenue). Net income is before preferred dividends. |
| revenue_growth | **Included** (14 of 20) | TTM total net revenue vs TTM a year earlier. SideDeck definition; FD semantics unverified. |
| debt_to_equity | **Calculated, excluded — owner definition approval required** | `borrowings_excluding_deposits` = DebtLongtermAndShorttermCombinedAmount / StockholdersEquity. Deposits and deposits+borrowings/equity are reported as context. |
| free_cash_flow_per_share | **Not meaningful** | `PaymentsForOriginationAndPurchasesOfLoansHeldForSale` is tagged: loan originations run through operating cash flow (TTM OCF − capex ≈ −$8.8B at 2026-06-30). Audit only, never per share. |
| book_value_per_share | **Excluded pending approval** | Earlier BVPS work is not reconciled/approved; the tool refuses an input that carries it. |
| gross_margin, operating_margin, current_ratio | **Not applicable** | No COGS/gross profit line, no operating-income subtotal, unclassified balance sheet. |
| market_cap, P/E | **Evidence pending** | See valuation below. |

### Reconciliation outcome

All net-margin inputs reconcile from 2022-06-30 to 2026-06-30. The three 2021–Q1 2022
periods show `MISMATCH`. This is a real data discontinuity, not a tool error: the
Q1 2021 10-Q belongs to the pre-merger SPAC (the SoFi business combination closed
in May 2021), so its YTD figure does not chain with SoFi's later 3-month facts.
Those periods stay excluded. Revenue growth for 2021–2022 fails for the same reason.

Latest values (2026-06-30, available 2026-08-06): net margin 0.1478, revenue growth
0.4080, borrowings/equity 0.2980 (excluded). These are SEC-derived research values,
not validated investment signals.

## Valuation evidence (audit only)

There are 11 market-cap candidates, from the FY2023 10-K (filed 2024-02-27) to the
Q2 2026 10-Q. The local price file starts 2024-01-02, so earlier filings report
`PRICE_WINDOW_UNAVAILABLE`. The latest candidate is 1,291,570,324 shares
(as of 2026-07-31) × $18.38 (IEX close 2026-08-07) ≈ $23.7B. No numeric P/E is
emitted, consistent with `P5_VALUATION_EVIDENCE.md`. Statuses are
`P_E_VALIDATION_PENDING` from 2024-09-30 on and `P_E_NOT_MEANINGFUL` while TTM net
income was negative.

Outstanding validation gaps: IEX-only (not consolidated) closes; the share-count
date precedes the price date; share-class completeness is unverified; split-adjusted
prices are not reconciled against unadjusted share counts.

## Coverage gate (bank profile)

```
moat               FULL         return_on_equity, net_margin
management         NO_EVIDENCE  earnings_per_share is annual-only, absent in newest period
financial_strength NO_EVIDENCE  debt_to_equity awaiting definition approval
valuation          NO_EVIDENCE  market cap / P/E not validated
relevant fields in newest period: 3/7   ->   coverage_gate = FAIL
```

Prompt size with the new input is about 931 input tokens for one call. The 4,096-token
Anthropic output cap is an upstream client setting, **not** an independently
enforced dollar limit.

## Owner decisions needed (none are requests to call a provider)

1. **Debt/equity definition**: approve `borrowings_excluding_deposits` for
   SOFI, or leave financial strength unassessed. The approval is a CLI flag:
   `--approve-definition debt_to_equity:borrowings_excluding_deposits`.
2. **Management evidence**: newest-period EPS is unavailable because the
   pipeline uses only directly filed full-year diluted EPS. Options: accept a
   lagged annual figure, or approve a quarterly TTM EPS definition. Summing
   quarterly diluted EPS is an approximation because share counts change.
3. **Valuation**: obtain consolidated (SIP) closes or another corroborating
   source before any market-cap candidate enters the input.
4. **Acceptance instrument**: SOFI is a poor *first* acceptance case. The SPAC
   history breaks pre-2022 continuity, 5 of 12 Buffett fields are inapplicable
   or excluded, FCF is not meaningful, and leverage needs a sector definition.
   Recommendation: run the first two-agent acceptance on a non-financial
   company with conventional statements and keep SOFI as the second,
   sector-specific case.

## Commands (from `sidedeck/`, PowerShell)

```powershell
.\.venv\Scripts\python.exe -m sidedeck.application.p5_sec_bank_metrics `
  --companyfacts data/sofi-companyfacts-raw.json --base-input data/sofi-buffett-roe-eps-v2.json `
  --as-of 2026-10-19 --cik 1818874 --output data/<new>.json --audit-output data/<new-audit>.json
.\.venv\Scripts\python.exe -m sidedeck.application.p5_market_cap_evidence `
  --companyfacts data/sofi-companyfacts-raw.json --prices data/sofi-alpaca-iex-full.json `
  --ticker SOFI --as-of 2026-10-19 --output data/<new>.json
$env:PYTHONPATH = (Resolve-Path ".\src").Path
& "..\ai-hedge-fund\.venv\Scripts\python.exe" -m sidedeck.application.p5_buffett_coverage `
  --fundamentals-json data/sofi-buffett-bank-v3.json --ticker SOFI --as-of 2026-10-19 --sector-profile bank
```
