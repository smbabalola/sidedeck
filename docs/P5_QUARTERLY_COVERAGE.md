# P5 quarterly SEC coverage audit

This is an intermediate research-only evidence check, **not** an AI Hedge Fund Buffett snapshot. It reads the already downloaded SEC multi-metric preview, intersects exactly matching report periods from TTM net income, TTM operating cash flow, ROE and filed shareholders' equity, and records each observation's earliest complete filing availability and original SEC accession evidence. Any missing series removes that quarter from the complete-period intersection; malformed or future evidence fails closed. The output explicitly identifies still-missing Buffett agent metrics.

```powershell
.\.venv\Scripts\python.exe -m sidedeck.application.p5_quarterly_coverage --input data/sofi-multimetric-v5.json --output data/sofi-quarterly-coverage-v1.json
```

No network or AI calls are made. The output is a local JSON audit. Do **not** feed this audit directly into `filed_fundamentals.py`: it is not the upstream `FinancialMetrics` contract. In particular, an equity-to-liabilities ratio is **not** debt-to-equity; no gross/operating/net margin, revenue growth, FCF/share, earnings-per-share TTM or historical market-cap valuation is fabricated.

Remaining: reconcile financial definitions to actual `hedge_fund.data.models.FinancialMetrics` fields, validate quarterly timings and ratios, check point-in-time publication dates, then run the genuine Buffett persona in research-only mode. Buffett remains NO-GO and all broker execution stays disabled.
