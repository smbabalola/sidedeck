# SD-143 five-minute source comparison

**Status (27 October 2026): BLOCKED_EXTERNAL. No provider is recommended or enabled.**
No credentials were read and no authenticated data requests were made. Alpaca is
considered only as a possible *data-only* source; SideDeck retains all portfolio,
risk, approval and execution control. Whether its data may lawfully support
decisions subsequently executed through eToro Demo is not established here.

## Candidate comparison

| Source | Publicly documented access | Material limits and open questions | Decision |
|---|---|---|---|
| Alpaca Trading API market data | Current docs describe Basic (free, IEX, 15-minute delayed API) and Algo Trader Plus ($99/month, SIP/all US exchanges, no historical 15-minute restriction); equities history is documented since 2016. A paper account can use the shared market-data host, but account-specific entitlement is not verified. [Market Data API](https://docs.alpaca.markets/us/docs/about-market-data-api), [pricing](https://alpaca.markets/data), [authentication hosts](https://docs.alpaca.markets/us/docs/authentication) | Terms say personal/non-commercial use, refer paid plans to exchange agreements, and require advance notice for making a user application available to others. Support says API data cannot be redistributed. These materials do not establish SideDeck's use case, its eToro cross-broker use rights, storage/replay rights, or exact bid/ask five-minute coverage for an eligible account. No data download or subscription approved. [Terms](https://files.alpaca.markets/disclosures/library/TermsAndConditions.pdf), [redistribution FAQ](https://alpaca.markets/support/redistribute-alpaca-api) | Candidate for legal/contract review only; **not approved**. |
| eToro market data | SideDeck's prior one-shot AAPL instrument-search call returned HTTP 403; permission is consumed. | No further eToro calls are authorized. That search response did not establish five-minute history entitlement, full-session bid/ask coverage, data reuse, latency, or cross-broker use. Current API-specific data terms have not been verified. | Blocked. No retries. |
| Other licensed sources | No source selected. | Must establish instrument coverage, history depth, five-minute bid/ask, timestamps, split/dividend treatment, delay, access plan, replay/storage and cross-broker decision rights before acquisition. | Research only; no purchase or requests. |

## Consequence for SD-142/144

SD-142 accepts only normalized local rows with immutable source, entitlement,
instrument mapping, corporate-action and adjustment provenance. The fixture
pipeline marks all outputs `strategy_admission_eligible: false` and
`broker_execution: DISABLED`. SD-144 cannot use these fixtures as market evidence.
Before acquisition, the owner must resolve provider terms and account-specific
entitlement and approve a fixed provider, endpoint, date range, symbol list,
request count, cost ceiling, and data-retention/replay use. No authenticated
acquisition is included in this decision.

**Reviewed 2026-10-27 against official public pages.** Pricing, plans and terms
can change; re-check them before any later authorization. Public documentation
is not account-specific legal advice or an entitlement grant.
