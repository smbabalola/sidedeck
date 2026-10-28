# SD-143 five-minute source comparison

**Status (28 October 2026): Alpaca is the owner-preferred market-data candidate for the initial SWING strategy; SD-143 remains BLOCKED_EXTERNAL. No provider is enabled or approved for new authenticated requests.**
The owner has decided to keep Alpaca for now and **defer selecting an alternative provider for intraday trading**. Reuse already-qualified existing Alpaca research datasets; verify their provenance, licence/entitlement and sufficiency for SWING admission. Codex must not purchase a plan, download new data or perform credentialed reads from this decision alone. eToro remains the intended Demo execution and price-validation broker, subject to separately approved access. SideDeck retains all portfolio, risk, approval and execution control. Whether Alpaca data may lawfully support decisions executed through eToro Demo remains unverified.

## Candidate comparison

| Source | Publicly documented access | Material limits and open questions | Decision |
|---|---|---|---|
| Alpaca Trading API market data | Current docs describe Basic (free, IEX, 15-minute delayed API) and Algo Trader Plus ($99/month, SIP/all US exchanges, no historical 15-minute restriction); equities history is documented since 2016. A paper account can use the shared market-data host, but account-specific entitlement is not verified. [Market Data API](https://docs.alpaca.markets/us/docs/about-market-data-api), [pricing](https://alpaca.markets/data), [authentication hosts](https://docs.alpaca.markets/us/docs/authentication) | Terms say personal/non-commercial use, refer paid plans to exchange agreements, and require advance notice for making a user application available to others. Support says API data cannot be redistributed. These materials do not establish SideDeck's use case, its eToro cross-broker use rights, storage/replay rights, or exact bid/ask five-minute coverage for an eligible account. No data download or subscription approved. [Terms](https://files.alpaca.markets/disclosures/library/TermsAndConditions.pdf), [redistribution FAQ](https://alpaca.markets/support/redistribute-alpaca-api) | Candidate for legal/contract review only; **not approved**. |
| eToro market data | SideDeck's prior one-shot AAPL instrument-search call returned HTTP 403; permission is consumed. | No further eToro calls are authorized. That search response did not establish five-minute history entitlement, full-session bid/ask coverage, data reuse, latency, or cross-broker use. Current API-specific data terms have not been verified. | Blocked. No retries. |
| TradingView (visual research / Pine Script) | TradingView states that it has **no public API for fetching market data or indicator values**; its charting libraries also require an externally supplied datafeed. The UI supports discretionary charting and manual strategy exploration. [Official market-data API FAQ](https://www.tradingview.com/support/solutions/43000474413-i-need-access-to-your-api-in-order-to-get-data-or-indicator-values/) and [charting datafeed docs](https://www.tradingview.com/charting-library-docs/latest/connecting_data/datafeed-api/) | **Not an eligible source for autonomous SideDeck trading or programmatic data ingestion under published standard terms.** TradingView's [terms, section 3](https://www.tradingview.com/policies/) explicitly prohibit non-display algorithmic decision-making and automated orders using its market data, including data carried via alerts and webhooks. Do not scrape charts, use unofficial API wrappers or turn TradingView webhooks into automated trade signals; no such permission is assumed. A separately negotiated written licence would need explicit rights before reevaluation. | **Manual visual research only; not an SD-143 automated feed, SD-144 admission dataset, or autonomous webhook trigger.** |
| Other licensed sources | No source selected. | Must establish instrument coverage, history depth, five-minute bid/ask, timestamps, split/dividend treatment, delay, access plan, replay/storage and cross-broker decision rights before acquisition. | Research only; no purchase or requests. |

## Initial SWING versus deferred intraday sourcing

- **Initial SWING / research:** prefer **Alpaca existing historical SIP evidence**. Determine whether approved daily-bar research and point-in-time adjusted data are sufficient. Existing five-minute admission requirements remain in force until independently reviewed and formally updated for the SWING track; no shortcuts to executable strategy admission.
- **Broker execution pricing:** separately verify fresh eToro Demo instrument mapping, bid/ask and quote timestamps under a new signed read scope; Alpaca historical prices must not be presented as executable eToro quotes.
- **Future intraday:** postpone choosing or subscribing to an intraday-specific vendor. TradingView stays visual/manual research only under current terms; FinancialData.Net or other vendors can be reviewed later without disrupting the SWING launch work.
- **Access:** source preference alone is not permission for Alpaca or eToro authenticated calls, purchases, storage/redistribution or cross-broker use.

## Consequence for SD-142/144

SD-142 accepts normalized local rows through the provider-neutral
`FiveMinuteProvider` contract. Its eToro fixture adapter reuses the SD-119
identity and bid/ask parser and hashes the exact payload; it marks entitlement,
instrument mapping, corporate-action and adjustment status unverified, which
the session validator quarantines. A separately supported verified local parser
may supply independently established provenance. Accepted manifests are sealed
through SideDeck's research `SourceSigner`. All outputs remain
pipeline marks all outputs `strategy_admission_eligible: false` and
`broker_execution: DISABLED`. SD-144 cannot use these fixtures as market evidence.
Before acquisition, the owner must resolve provider terms and account-specific
entitlement and approve a fixed provider, endpoint, date range, symbol list,
request count, cost ceiling, and data-retention/replay use. No authenticated
acquisition is included in this decision.

**Original provider review 2026-10-27; TradingView API and terms reviewed 2026-10-28 against official public pages.** Pricing, plans and terms
can change; re-check them before any later authorization. Public documentation
is not account-specific legal advice or an entitlement grant.
