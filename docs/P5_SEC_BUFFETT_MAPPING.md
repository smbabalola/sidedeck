# P5 SEC-to-Buffett research mapping — limited ROE coverage

SideDeck can now transform the existing quarterly coverage audit into the **shape** accepted by `LocalFiledDataClient`: `{ticker, records}` with filing-dated TTM report periods, an SEC filing archive source locator, and source-backed ROE. A **separate audit** retains all component accessions and a list of important Buffett fields intentionally not mapped.

Example, from SideDeck PowerShell:

```powershell
git pull --ff-only
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m sidedeck.application.p5_sec_buffett_mapping --quarterly-coverage data/sofi-quarterly-coverage-v1.json --cik 1818874 --output data/sofi-buffett-roe-v1.json --audit-output data/sofi-buffett-roe-audit-v1.json
```

This mapping makes **no network calls or AI requests**. It retains the first eligible sourced ROE, and refuses malformed SEC accession IDs, future evidence, duplicate periods, or fewer than four observations. It is schema-compatible partial data, not a Buffett-qualified comprehensive financial snapshot.

The output may pass the existing `verified_fundamentals` schema validator, but Buffett scoring is **not** approved with ROE alone. Missing valuation, debt, growth, FCF and profitability measures must be independently established. The generated SEC archive folder URL is a provenance **locator**, not proof that a particular accession contains every derived financial ratio; the separate audit supplies the component lineage.

No LLM calls and no broker execution are authorized. A no-LLM snapshot probe with this file would only establish compatibility, never investment signal readiness. Current stage remains **NO_GO**.
