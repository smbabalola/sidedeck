# SD-023 corporate-action and benchmark audit

Status: `VERIFIED` on the exact CI head recorded in `TODO.md`. This is an
offline audit of the existing ignored SD-021 Alpaca SIP bundles; it made no
network request and does not change their admission status.

## Method

`sd023_corporate_action_audit.py` independently reads each saved bar bundle,
checks sorted unique dates, compounds close-to-close returns, calculates the
price-only maximum drawdown, and reconciles the ending equity to the saved
research report. It does not trust a reported `corporate_actions_verified`
boolean and never treats a split-adjusted close as a dividend-reinvested
total-return series.

| Ticker | Sessions | Start close | End close | Price-only equity | Return | Max DD | Research equity | Reconciliation |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| SPY | 1,254 | 453.59 | 769.05 | 1.695474 | 69.55% | 25.36% | 1.695474 | RECONCILED |
| QQQ | 1,254 | 377.27 | 717.63 | 1.902166 | 90.22% | 35.62% | 1.902166 | RECONCILED |
| MSFT | 1,254 | 310.76 | 531.87 | 1.711514 | 71.15% | 37.56% | 1.711514 | RECONCILED |

These are price-only benchmark figures, not investor total returns. Dividends,
distributions, withholding, and reinvestment are unavailable in the bundles.

## Corporate-action findings

- MSFT: the existing local official-source record identifies the latest 2-for-1
  split as effective 2003-02-18, no split in the 2021-10-21 through 2026-10-20
  window, and a $0.91 dividend with 2026-08-20 ex-date. The split basis is
  compatible with the `adjustment=split` bars; dividends are excluded from the
  close series. Status: `VERIFIED` for this limited window/basis audit.
- SPY and QQQ: no approved local ETF split/distribution evidence was present.
  Status: `NOT_ASSESSED`; no ETF total-return or distribution claim is made.

The audit therefore does not upgrade SD-004. Independent complete price
corroboration and a date-consistent share basis remain required for valuation;
broker execution remains disabled.

## Evidence and limitations

- Inputs: ignored local `data/sd021-{spy,qqq,msft}-sip.json` and corresponding
  research JSON reports; raw bytes remain untracked.
- Outputs: ignored `data/sd023-*-audit.json` files.
- Code/tests: `src/sidedeck/application/sd023_corporate_action_audit.py` and
  `tests/test_sd023_corporate_action_audit.py`.
- No authenticated broker request, paid data/model call, order, account read,
  or credential access occurred.
