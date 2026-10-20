# eToro v1 authenticated market-data access — 20 October 2026

**Workstream:** SideDeck P5 agent adapters (`feat/p5-agent-adapters`).
**Status:** MARKET_DATA_READ_OK. **Not** evidence of Demo portfolio read/write access or trading authorization.

## One-shot AAPL API probe (user-provided sanitized results)

- Method: `GET`
- Endpoint: `https://public-api.etoro.com/api/v1/market-data/search?internalSymbolFull=AAPL`
- Credentials: `ETORO_API_KEY` and `ETORO_USER_KEY` loaded locally from `.env`, both present (values never collected, printed or committed).
- Request count: **1** for the successful probe; no retries or redirects.
- Request header: `User-Agent: SideDeck/0.1 (read-only market-data probe)`.
- `x-request-id`: `9bd24634-97f5-4b84-84cf-e7c58a4b1919`
- HTTP status: **200**
- Server: `cloudflare`; CF-Ray: `a4d6dd6c8cb5e539-LHR`
- Classification: `MARKET_DATA_READ_OK`
- Selected **exact** symbol: `AAPL` / Apple / Nasdaq / `instrumentId=1001` / `internalInstrumentId=1001`.

The response also contained distinct symbols that must **not** be conflated with standard AAPL:

| Symbol | Instrument ID | Exchange/display |
| --- | ---: | --- |
| AAPL | 1001 | Apple / Nasdaq |
| AAPL.24-7 | 15569 | Apple 24/7 / NYSE |
| AAPL.EUR | 14254 | Apple / FRA |
| AAPL.RTH | 8754 | Regular Trading Hours - RTH |

## Earlier failure and interpretation

The prior one-shot request returned HTTP 403 with Cloudflare error **1010** using the default Python urllib user-agent. Changing the User-Agent to the transparent SideDeck identifier, with the same keys and one GET, returned HTTP 200. This is consistent with a client-signature block, but does not prove the precise Cloudflare rule. Earlier v1/v2 HTTP 403s alone cannot establish invalid API keys.

## Confirmed and outstanding gates

- [x] Local eToro credentials present (keys not disclosed).
- [x] Authenticated eToro v1 market-data search succeeded.
- [x] Exact Nasdaq AAPL instrument identified, ID 1001.
- [x] eToro **Demo** portfolio read permission confirmed: one authenticated GET HTTP 200 on 2026-10-20; see `ETORO_DEMO_READ_2026-10-20.md`.
- [x] Demo P&L response field schema observed, with 4 existing positions and 0 pending orders; no values printed.\n- [ ] eToro Demo cash, positions and open-order **value-level reconciliation** (read-only adapter not built).
- [ ] Demo-only order execution authorization and complete idempotent lifecycle (separate future review).
- [ ] Real-money execution must remain disabled.

No eToro orders were submitted by these probes. Saxo P4 remains `P4_DECISION=NO-GO` and `SIM_SUBMISSION_RELEASED=False`; Alpaca unchanged.

**Next:** implement and test a fail-closed **read-only eToro Demo portfolio adapter** offline. Do not submit orders or use real-money endpoints. See `ETORO_DEMO_READ_2026-10-20.md` for sanitized evidence and safeguards.

References:
- https://api-portal.etoro.com/guides/get-instrument-id
- https://api-portal.etoro.com/getting-started/authentication
- https://api-portal.etoro.com/guides/calculate-profit-loss
