# SideDeck threat model — Phase 0/P1

## Trust boundaries

The primary boundary is between future untrusted research workers and SideDeck's policy/accounting core. A second boundary will exist between SideDeck and eToro. P1 contains neither worker execution nor broker connectivity.

## Threats and controls

| Threat | Control |
|---|---|
| Prompt injection requests secrets or execution | Agents receive no broker secrets; P2 adapters return proposals only |
| Malformed or prohibited intent | Pydantic validation precedes allowlist and accounting checks |
| Stale, future, or fabricated quote | Timestamp, quality, session, positivity, and freshness gates; no random fallback |
| Portfolio cross-contamination | Portfolio ID is required on events; replay filters by portfolio |
| Duplicate events or retries | Per-portfolio idempotency keys and append-before-replay atomic validation |
| Manual balance mutation | Append-only journal and deterministic replay |
| Upstream side effects | Separate pinned checkout; no upstream framework installed or run in P1 |
| Demo/Real endpoint confusion | No broker client in P1; future demo capability must fail closed on real paths |
| Supply-chain or licensing risk | Locked dependencies; AI Trading remains unlicensed and external |

## P1 invariants

1. P1 has no broker HTTP path and no credentials.
2. A `TradeIntent` is data, not an executable order.
3. Missing or invalid marks never become zero-valued positions.
4. Failed validation creates no journal mutation.
5. Timestamps stored by SideDeck are timezone-aware UTC.

## Residual risk

P1 does not establish the safety of model providers, upstream dependencies, market-data vendors, or eToro. Those remain explicit P2–P5 gates.
