# Alpaca historical price acquisition — research-only

The adapter supports explicitly selected historical `iex` and `sip` feeds
with a persistent request budget. The 2026-10-21 authorized MSFT SIP retrieval
used one request and produced 59 local bars; see `docs/SD004_MARKET_DATA_PLAN.md`.
The raw bundle, budget and manifest are ignored local evidence and must not be
committed.

SideDeck has an opt-in downloader at `sidedeck.application.p5_alpaca_history` for the Alpaca **market-data** API `https://data.alpaca.markets/v2/stocks/{symbol}/bars`. It requests `timeframe=1Day`, `feed=iex`, `adjustment=split`, paginates bounded responses, validates positive closes, and refuses overwriting an output file. It **never calls trading/account/order endpoints**.

Alpaca's IEX data represents a single exchange, not the consolidated US SIP tape. Its split-adjusted prices need independent validation against SEC EPS split/share conventions before any P/E is trusted. Accordingly the downloader sets `corporate_actions_verified=false`; this **does not pass** SideDeck's downstream historical P/E validation gate until separately reviewed. No source or trading completeness claims should be inferred from successful download.

From PowerShell in the SideDeck checkout, with actual Alpaca **market-data** key-ID and secret environment variable names:

```powershell
.\.venv\Scripts\python.exe -m sidedeck.application.p5_alpaca_history --ticker SOFI --start 2024-01-01 --end 2026-10-18 --env-file .env --key-id-env APCA_API_KEY_ID --secret-env APCA_API_SECRET_KEY --budget-file data/sofi-alpaca-iex-budget.json --global-budget-file data/alpaca-global-budget.json --output data/sofi-alpaca-iex.json
```

If your local `.env` uses different variable names, pass those names with `--key-id-env` and `--secret-env`. **Never paste the actual values into PowerShell commands or chat**; only pass variable names. Some accounts use a different key naming convention; no naming is presumed or auto-selected from unrelated broker credentials. Existing `ALPACA_API_KEY2` may represent the key ID, but the secret variable name must be identified locally. The output contains neither secrets nor credentials.

No price fetch is needed to run offline tests. Permission errors (401/403), no bars or rate limits are blockers; do not change `feed` to paid SIP silently or work around access restrictions. CLI uses an explicit date range. Check Alpaca's market data entitlement/licensing before redistributing data.

References:
- https://docs.alpaca.markets/us/reference/stockbars
- https://docs.alpaca.markets/us/docs/market-data-faq

Next acceptance: actually retrieve SOFI IEX bars, compare them to independent daily closes and corporate actions, then reconcile SEC annual diluted EPS against share adjustment dates and source-backed prices. Buffett readiness and all broker execution remain NO-GO.
