# Saxo SIM US stock candidate shortlist

The SideDeck agent portfolios each hold USD 1,000; no live account or real-money trading is permitted. Saxo broker precheck of **one AAPL share** returned Ok but estimated **EUR 364.02**, above the current conservative EUR 200 per-order ceiling. This command discovers other reviewable **NASDAQ** stock candidates rather than forcing AAPL through the gate.

```powershell
git pull --ff-only
.\\.venv\\Scripts\\python.exe -m sidedeck.application.saxo_candidate_shortlist --expected-account-id "22866064"
```

The fixed reviewable discovery list is F, SOFI, PLTR, PFE, T, INTC. Only `<ticker>:xnas` and matching USD/Stock details are reported as CANDIDATE. A missing NASDAQ listing is not a failure of Saxo itself. Candidates are **not ranked** and are not approved for an order: the command retrieves neither prices nor prechecks and cannot estimate affordability. The next stage must precheck a specific candidate against the broker and independently verify data currency, quotes, FX costs and the USD 1,000 agent ledger. There is no order-submit code in this command.
