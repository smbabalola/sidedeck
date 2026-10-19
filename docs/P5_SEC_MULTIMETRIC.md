# P5 SEC multi-metric research preview

Run `python -m sidedeck.application.p5_sec_multimetric --help` for the CLI. It makes one official SEC Company Facts request using the required real contact User-Agent and writes a local JSON research preview without overwriting a prior file. The output contains original-source US-GAAP annual/interim observations for net income, operating cash flow, assets, liabilities and stockholders' equity, plus the separately implemented net-income TTM series.

**The output is not a verified valuation model or a Buffett-compatible financial snapshot.** Reported cash-flow durations (quarter/YTD/annual) are not comparable without normalization. Assets, liabilities and equity are instant balances, not TTM values. No share-count adjustments, split-aware EPS, audited cash-flow TTM or financial ratios have been computed. Per-metric cutoff and earliest-filed provenance are retained, but the SEC JSON remains subject to upstream data quality and filing verification.

For SOFI, use previously verified CIK 1818874 and a real user contact email, choosing a new local output filename. Do not push acquired exports to GitHub without reviewing access/licensing and source accuracy.

Paid OpenAI research, strategy signals, Saxo SIM submission and all live order capabilities remain outside this module and disabled.
