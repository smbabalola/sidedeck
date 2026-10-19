# Independent filing-dated fundamentals input (P5, experimental)

SideDeck now accepts a **local JSON input containing externally verified SEC filing-dated TTM financial records** through the research-only AI Hedge Fund Buffett bridge. It does **not** download or compute these records yet. A URL string is provenance metadata, **not** proof that the numbers match the SEC filing. Operators must verify each filing, accounting period, currency, units, split adjustments and metric derivation before using the result in research. A file containing invented/placeholder figures is not acceptable.

Format: JSON object with `ticker` and `records` list. Each record needs `report_period` (YYYY-MM-DD), `filing_date` (YYYY-MM-DD), `period` exactly `ttm`, and `source_url` pointing to the relevant SEC filing; add only supported financial metric keys in `filed_fundamentals.py`. Four or more distinct, publicly filed TTM periods must be available by the chosen cutoff. Future records are excluded; missing/duplicate provenance fails closed. This experimental importer is NOT an audited SEC XBRL calculation engine.

The research launcher now accepts `--fundamentals-json <absolute-verified-file>`, used only by the AI Hedge Fund bridge; TradingAgents continues to use its own upstream data pipeline. Because the two upstream data feeds are not comparable yet, no head-to-head fairness, strategy profitability, model-cost, real historical accuracy or SIM readiness claim is warranted.

**Safety**: Research only, no Saxo order or risk approval. Never commit provider keys or locally acquired financial records before reviewing licenses and provenance. Avoid placing made-up data in fixtures outside explicitly synthetic tests.

## Outstanding for authentic free-data operation

Build a tested SEC EDGAR Company Facts downloader (SEC identification/User-Agent, lawful rate limits), historical XBRL point-in-time metric conversion and filing/units provenance trail. Validate its output against original filing records, then run upstream BuffettAgent with the user's authorized OpenAI account. These steps are not yet implemented. Do not trigger paid model requests without operator consent.
