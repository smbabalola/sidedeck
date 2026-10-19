# Experimental SEC XBRL TTM converter

`sidedeck.application.p5_sec_ttm` downloads official SEC Company Facts with the same single-request bounded transport as `p5_sec_edgar` and reconstructs a **single metric**: NetIncomeLoss in USD, where an original annual 10-K, the current-year 10-Q year-to-date number, and the prior-year matching 10-Q year-to-date number exist. It computes **TTM = previous annual + current YTD - comparable prior YTD**.

Each result retains original accession, form, filing date, reporting start/end and XBRL tag for every input. Values unavailable by the cutoff are excluded. Records lacking reliable matching periods are skipped. This is a partial *research preview*, not a full audit of fiscal-calendar changes, amended filings, issuer comparability or SEC taxonomy variations.

Example (replace the sample email with a real SEC contact email):

```powershell
.\.venv\Scripts\python.exe -m sidedeck.application.p5_sec_ttm --cik 1818874 --ticker SOFI --as-of 2026-10-19 --user-agent "SideDeck Research contact@example.com" --output data/sofi-net-income-ttm.json
```

The output declares `buffett_ready: false`. **Do not pass it to `--fundamentals-json`**: Buffett requires a comprehensive, reliably derived point-in-time metrics history, not net income alone. No LLM or trading orders are involved.

Missing before first paid AI research test: validated multi-metric ratios/per-share history, periodicity assurance, realistic provenance and data quality review; upstream model compatibility, date-consistent inputs, LLM-call approval. No Saxo SIM or live execution.
