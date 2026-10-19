# P5 SEC annual diluted EPS reconciliation and stable property test

The SEC multi-metric preview now includes `annual_diluted_eps_ttm`, consisting solely of **directly reported 10-K full-year diluted EPS** observations, preserving original SEC accession, filing date, reporting start/end and USD/shares unit. A full-year diluted EPS figure is a trailing-year observation **at that fiscal year end**, but this does **not** produce quarterly-rolling TTM EPS.

**Do not sum diluted quarterly or YTD EPS**: weighted-average diluted denominators, antidilution treatment, capital actions and loss-period share counts can make the resulting value wrong. No historical P/E is calculated and no market prices have been sourced yet. A verified price feed, split/corporate-action conventions and a date-consistent share history must be established before P/E or Buffett readiness can be approved.

The property-based accounting replay test still checks cash conservation and repeated-fill idempotency for 25 generated examples. On this single test, the Hypothesis `HealthCheck.too_slow` diagnostic is suppressed to avoid intermittent Windows input-generation scheduling failures. **No test data, assertions, Hypothesis examples, or accounting logic were reduced.**

Research only. Neither change calls an AI provider or a broker.
