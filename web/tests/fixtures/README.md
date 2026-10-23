# Frontend test fixtures

Generated from the real SideDeck backend summary functions against a throwaway
SQLite file and the SD-076 synthetic scanner. They are **test fixtures**: the four
"protected positions" and every scan row are fabricated for UI testing and are
never market data, broker data or performance evidence.

`market-uk.json` comes from `sd097_uk_markets_api.uk_markets_summary` at a fixed clock
with no licensed UK data directory (genuine panels are `UNAVAILABLE`) and an SD-096 report
whose scan is `SYNTHETIC_FIXTURE` (ZZ ISINs) and whose trade is `SIMULATION`.
