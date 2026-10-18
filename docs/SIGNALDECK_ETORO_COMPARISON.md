# SideDeck / SignalDeck — eToro authentication success investigation

**Date:** 2026-10-18
**Type:** Read-only code/previous acceptance comparison. **No authenticated API calls made**. No secrets or key fingerprints copied.

## Original code source and reported historical acceptance

The owner has a private GitHub repo **`smbabalola/SignalDeck`**, default branch `bundle7/complete-demo-lifecycle` at reviewed HEAD `8c45b45dd14bb47f774205f8bb311fedaae649f5`.

Verified source paths:
- [SignalDeck REST client](https://github.com/smbabalola/SignalDeck/blob/bundle7/complete-demo-lifecycle/backend/app/adapters/market_data/etoro/client.py), `search_instruments`, `get_candles`, `_headers`, and `HttpClientEtoroTransport`.
- [SignalDeck settings](https://github.com/smbabalola/SignalDeck/blob/bundle7/complete-demo-lifecycle/backend/app/settings/config.py), `Settings` with `env_file=".env"`, `ETORO_API_KEY`, `ETORO_USER_KEY` validation aliases and `ETORO_ENVIRONMENT` default `demo`.
- [SignalDeck opt-in smoke test](https://github.com/smbabalola/SignalDeck/blob/bundle7/complete-demo-lifecycle/scripts/etoro_live_smoke.py), which uses real `search_instruments`, `get_rates` and `get_candles`.
- [SignalDeck client unit tests](https://github.com/smbabalola/SignalDeck/blob/bundle7/complete-demo-lifecycle/tests/unit/test_etoro_client.py) verify fresh `x-request-id` UUIDs, key header names, no `Authorization`, and response handling.

Per the **owner's September 27 local test reports (not independently reproduced in this October review)**, normal Windows PowerShell obtained HTTP 200 from eToro Demo portfolio, market search, quotes and daily candles using the intended key pair. Earlier SignalDeck Codex/sandbox requests sometimes got HTTP 403 for ostensibly the same endpoints, while direct user PowerShell returned HTTP 200. The successful historical request is valuable but does **not prove the current SideDeck credentials are byte-equal to the then-loaded credentials**, or guarantee endpoint availability today.

## Concrete technical differences

| Detail | SignalDeck | SideDeck |
|---|---|---|
| Base | `https://public-api.etoro.com` | `https://public-api.etoro.com/api/v1` |
| Actual search route | `GET /api/v2/market-data/instruments/search?query=AAPL&limit=5` in smoke | `GET /api/v1/market-data/search?internalSymbolFull=AAPL` |
| Search response | `{"results":[{"instrumentId":...,"symbol":...,"type":...}]}` | `{"items":[{"internalInstrumentId":...,"internalSymbolFull":...,"assetType":...}]}` expected |
| Candle route | `GET /api/v1/market-data/instruments/{id}/history/candles/asc/OneDay/10` in smoke; runtime also supports desc | `GET /api/v1/market-data/instruments/{id}/history/candles/backward/OneDay/1000` |
| Auth request | `Accept: application/json`, `x-api-key`, `x-user-key`, new `x-request-id` UUID | Same names and UUID |
| HTTP transport | `http.client.HTTPSConnection` as default (direct connection) | `urllib.request.build_opener` with no redirects (inherits proxy settings by default) |
| Configuration | Pydantic Settings loads repo-root `.env`, with optional `SIGNALDECK_...` aliases | Earlier local probe explicitly loaded SideDeck `.env`, but plain PowerShell does not auto-load values |
| Account mode | `ETORO_ENVIRONMENT=demo` used by SignalDeck broker guard, **not market-data URL** | `ETORO_ENVIRONMENT` is unused in SideDeck `data_probe.py`; SideDeck user key UI shown as Main |
| Successful direct-shell access | User-reported Sept 27 HTTP 200 (multiple routes) | Oct 18 read-only AAPL v1 search returned HTTP **403** and stopped |

**Critical nuance:** eToro's **current official API guide** [Find Instrument ID](https://api-portal.etoro.com/guides/get-instrument-id) specifies SideDeck's **v1** search path and `internalSymbolFull` parameter. SignalDeck's older **v2** search might still be accessible, but this cannot be assumed. Do not change live route blindly or classify the 403 as proof of missing historical data.

## Root cause assessment

1. **Request-path/API-version differences:** real, source-verified and material. Most promising controlled comparison (when newly authorised) is the previously successful **SignalDeck v2 read-only market-data search**, not a speculative rewrite of candle paths.
2. **HTTP client/proxy/egress differences:** real, source-verified. Direct PowerShell versus Codex sandbox previously diverged. `urllib` can honor proxy environment variables; `http.client` default direct transport does not automatically use urllib proxy discovery. Compare security policy and environment **offline first**. Do not bypass required corporate/network egress protections.
3. **Credentials matching earlier working invocation:** no evidence of byte-equality between original SignalDeck local `.env` and current SideDeck `.env`. Owner confirms SideDeck `x-api-key` and `x-user-key` were created as the same pair; this is **not** proof that SignalDeck currently holds identical bytes. Compare locally with **boolean-only** equality output under strict secret suppression, never print, hash or upload keys.
4. **Portal entitlement:** owner UI shows Market Data — Read enabled, key active, no IP allowlist/expiry. This weakens but does not eliminate endpoint-level / tenant restrictions; 403 is not evidence of no data.
5. **Timing/API changes:** September success does not guarantee October compatibility; official support may need request ID and timestamp from the **owner's private logs** if available.

## Offline-only next tasks (no network permission)

- Compare the two local projects' actual **loaded** API/user keys with only booleans: `same_api_key`, `same_user_key`, `both_present`; do not print lengths, hashes, values or environment file content. Confirm each project root and which `.env` settings loader uses. Check whether `ETORO_ENVIRONMENT` affects URLs (it does not in either inspected market-data GET).
- Produce **dry-run/test-only** request-contract fixtures for SignalDeck v2 search and SideDeck v1 search with sanitized dummy credentials. Assert path/query/header structure, same-host HTTPS-only, redirect prevention, no broker endpoints, no nondeterministic remote work.
- Review proxy/TLS/HTTP behavior and documented security boundaries in the owner's terminal and Codex execution contexts *without opening connections*. Do not disable network protections or auto-test additional endpoints.
- Only after local audit, offer owner an explicit bounded scope for **at most one** read-only v2 instrument search, with fresh approval. Never reuse exhausted Oct 18 eToro test authorisation.
- If the dry-run request shape and local credentials match but a separately approved v2 read still fails, raise the discrepancy with eToro developer support using sanitized endpoint/status/time/request ID, never keys.

**Release note:** This comparison does not grant access to balances/positions, Demo or Real broker APIs, historical candle reads, Tiingo, or any paid provider. Continue offline SideDeck historical-data validation while eToro permissions are investigated.
