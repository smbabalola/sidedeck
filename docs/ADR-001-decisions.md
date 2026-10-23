# ADR-001 — SideDeck Phase 0 decisions

Status: Proposed  
Date: 2026-10-18  
Scope: P0 reconnaissance and P1 foundation boundary

## Decisions

1. P1 starts with typed contracts, deterministic accounting, a versioned experiment manifest, two isolated virtual portfolios, an append-only ledger, a fixed instrument registry, and as-of market snapshots.
2. P1 uses a deterministic in-memory simulator. No eToro credentials, broker HTTP client, broker write path, or account endpoint is included.
3. Agent outputs will be normalized to `TradeIntent`; agents cannot mutate SideDeck state directly.
4. Each portfolio starts with USD 1,000; long-only, no leverage, no crypto/CFDs/FX/shorts; maximum gross exposure 80%; maximum four positions; maximum 20% new-position notional; and a documented 1% intended-entry risk budget.
5. Missing, stale, future-dated, invalid, or fabricated prices fail closed. There is no random fallback or silent zero price.
6. External upstream checkouts remain outside the repository and are pinned by commit SHA. No upstream source is vendored in P1.
7. The design target is Python 3.12; the current machine is Python 3.13.16, so compatibility must be tested and documented.

## External references and permissions

- TradingAgents reviewed at `e8f5503e9b86d5c2710b0c76b1f686703968c9df`; Apache-2.0 `LICENSE` present. The inspected public API is `TradingAgentsGraph.propagate(company_name, trade_date, asset_type="stock", portfolio=None)`.
- AI Trading reviewed at `8f2e287e77851266b0d11ff2ba4a13c15793f79f`; no `LICENSE`, `COPYING`, or `NOTICE` file found. Do not vendor or redistribute pending rights review.
- eToro authentication requires `x-api-key`, `x-user-key`, and unique `x-request-id` headers. Current official product documentation shows demo execution under `/api/v2/trading/execution/demo/orders`; other read examples use `/api/v1`, so endpoint behavior must be verified individually in P5.

## Consequence

P1 remains useful without network access, model credentials, or broker access. Agent adapters and real/demo reconciliation remain deferred until the deterministic core is reviewed.
