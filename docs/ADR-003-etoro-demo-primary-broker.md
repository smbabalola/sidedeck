# ADR-003 — eToro Demo is the primary paper broker; Alpaca PAPER is secondary

**Status:** ACCEPTED (owner decision, 2026-10-21) | **Supersedes:** the broker priority implied by SD-032…SD-035 (Alpaca-first). It does not supersede any safety rule.

## Context

SD-032…SD-035 built broker-independent controls (durable outbox, verifier-only approvals, kill-switch, reconciliation contract) around Alpaca PAPER. SD-035 left Alpaca account separation `UNVERIFIED`: Pair B returned HTTP 401 and both authorizations are exhausted.

eToro Demo already has more verified groundwork:

- one owner-run Demo `/pnl` read returned HTTP 200 (2026-10-20);
- a captured, immutable four-position baseline matched on first reconciliation;
- a read-only, path-allowlisted client and strict parser exist.

eToro's public API reference documents separate Demo trading paths, order lookup by `referenceId`, and explicit Demo/Real and Read/Write key separation.

## Decision

1. **eToro Demo is SideDeck's primary paper-trading broker.** New paper-execution engineering targets eToro Demo first.
2. **Alpaca PAPER remains supported as secondary.** Its code, tests and evidence stay. Its account separation remains `UNVERIFIED`, and its authorizations remain exhausted.
3. **eToro Real execution is permanently excluded.** `require_demo_route` refuses every path without `/demo/`, and every path outside the documented Demo allowlist, before any network activity. This is not a toggle.
4. **Ownership comes from verified lineage only.** The chain is SideDeck `x-request-id` (`referenceId`) → `orderId` → `positionExecutions[].positionId`, where `openingData.orderId` must equal the order. Ticker or instrument matching is never ownership evidence.
5. **The four original Demo positions are a protected, unattributed baseline.** They can never be claimed, attributed or closed by SideDeck. A broker report naming one of them for a SideDeck order trips the kill-switch.
6. **The broker-independent Alpaca controls are reused unchanged in behaviour.** The SD-032 outbox runs with `broker="etoro"`, `account_scope="etoro-demo"`. SD-033 provides approvals and the kill-switch. Additive methods: `record_rejection` and `is_approved`.
7. **Agent Portfolios are not adopted.** See [SD036_ETORO_DEMO_CONTRACT_REVIEW.md §5](SD036_ETORO_DEMO_CONTRACT_REVIEW.md). They are documented with Real-account scopes, they fund by deducting the caller's balance, and they appear as a copy/mirror. Status: `NOT_ADOPTED_PENDING_EVIDENCE`.

## Consequences

- `ETORO_DEMO_EXECUTION_RELEASE = "NO_GO"`. The desk accepts only a transport that declares `offline_simulation=True`, and SideDeck contains no HTTP transport for Demo writes. Enabling one requires code review plus a separate, explicit owner release (G4).
- This is a change of broker **priority, not permission to trade**. No authenticated eToro request, credential access, order, position modification or automatic trading is authorized by this ADR.
- Paper release stays `NO_GO`, broker execution `DISABLED`, and Saxo P4 `NO-GO`.
