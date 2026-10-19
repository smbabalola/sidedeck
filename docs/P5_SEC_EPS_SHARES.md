# SEC diluted EPS and weighted-average diluted shares (P5 research only)

The multi-metric SEC export now includes `diluted_eps_reported` (US-GAAP `EarningsPerShareDiluted` in `USD/shares`) and `weighted_average_diluted_shares_reported` (US-GAAP `WeightedAverageNumberOfDilutedSharesOutstanding` in `shares`). Each observation preserves statement start/end, SEC accession, filing date, form and unit. Only 10-K/10-Q filings public by the chosen `as_of` date are included. For the same reporting duration the earliest qualifying filing is retained, instead of silently replacing an original with a later restatement.

**No P/E is calculated.** EPS observations can refer to quarterly, YTD or annual spans; weighted-average shares refer to their respective reporting span, not a point-in-time outstanding-share balance. Summing diluted EPS observations or casually dividing TTM net income by a current share count can yield invalid values (loss-period antidilution, changes in dilution, splits, issuer-specific adjustments). A licensed, historical market price source and verified matching TTM EPS/share convention are still required.

From the SideDeck checkout, pull changes, run tests, and rerun `sidedeck.application.p5_sec_multimetric` into a **new** file, for example `data/sofi-multimetric-v4.json`, with a genuine identifying SEC User-Agent. Then run `sidedeck.application.p5_fundamentals_gate --input data/sofi-multimetric-v4.json`. The gate will report coverage counts for the new observations and retain the P/E and Buffett blockers.

No LLM calls or broker orders are issued.
