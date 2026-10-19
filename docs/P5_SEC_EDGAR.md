# SEC EDGAR Company Facts download (experimental)

The P5 SEC loader makes one HTTPS request to the official SEC Company Facts API. It requires an identifying contact User-Agent, a numerical CIK, an explicitly selected ticker and an as-of cutoff. Data requests are bounded by a 20-second timeout and a 20 MB response cap. No AI model call and no broker request takes place.

From the SideDeck project directory, for the public SOFI issuer **CIK 1818874** (verify the identifier independently before use):

```powershell
.\.venv\Scripts\python.exe -m sidedeck.application.p5_sec_edgar --cik 1818874 --ticker SOFI --as-of 2026-10-19 --user-agent "SideDeck Research contact@example.com" --output "data/sofi-sec-annual.json"
```

Replace `contact@example.com` with your actual, reachable contact email for the SEC, and create the output directory first. The command refuses to overwrite an existing export. Review the SEC's current fair-access guidance and do not run high-frequency requests. The request does not read or send the SideDeck .env keys.

**Limitations:** Only selected US GAAP tags in 10-K filings, with USD units, are exported. For flow measures, observations must cover approximately an annual duration. Output includes source endpoint, SEC accession, public filed date, period-end and tag for each value. Later restatements are not substituted for the first eligible publication. Different metrics can have different earliest filing dates; this export is **not** a normalized point-in-time analyst dataset.

**Not yet implemented:** This exported annual JSON is intentionally **incompatible** with `--fundamentals-json`, which requires filing-dated quarterly-spaced trailing-twelve-month metrics; relabelling annual statements as TTM would cause misleading AI inferences. The missing conversion requires consistent quarterly derivations from annual and interim data, anti-restatement controls, currency/units checks, ratio calculations and verification against SEC source documents.

This work is a real-data downloader, **not** proof of a successful upstream AI agent run. Saxo SIM submission remains disabled.
