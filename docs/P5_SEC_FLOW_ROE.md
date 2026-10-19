# SEC cash-flow TTM and ROE preview

The SEC multimetric preview now includes `operating_cash_flow_ttm` reconstructed from annual and compatible prior/current YTD SEC cash-flow figures, and `return_on_equity_preview`, which divides filed net-income TTM by the mean of matched same-day year-apart shareholder equity balances. Each derived row carries its underlying SEC accession identifiers and filing dates. Missing comparators are skipped rather than guessed.

The fundamentals gate reports counts for `cash_flow_ttm_records` and `roe_preview_records` and remains **NO_GO** because a complete, reconciled Buffett snapshot has not been established. This is a preliminary calculation, not an audit or investment signal. The ROE convention here uses two endpoint equity balances, not an average of quarterly balances; for banks this is a simplifying accounting convention that must be assessed before decision use.

To refresh the saved SOFI preview, use a **new output path**, because exports refuse overwrite:

```powershell
.\.venv\Scripts\python.exe -m sidedeck.application.p5_sec_multimetric --cik 1818874 --ticker SOFI --as-of 2026-10-19 --user-agent "SideDeck Research CONTACT_EMAIL_HERE" --output data/sofi-multimetric-v2.json
.\.venv\Scripts\python.exe -m sidedeck.application.p5_fundamentals_gate --input data/sofi-multimetric-v2.json
```

Use a real SEC contact address. Do not upload local SEC files or API keys. Neither command sends a broker order or makes an LLM request. As historical-source validation, ticker mapping, share counts, prices and full accepted metrics remain incomplete, no Buffett research or trading is permitted.
