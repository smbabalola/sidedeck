# ADR-003: Bind strategy scope to a SideDeck book

**Status:** Accepted for offline implementation, 28 October 2026
**Scope:** SD-063 policy schema v3 and SD-138 composition only

## Context

SD-063 signed strategy scopes named strategy, version, track and evidence, while the
durable SD-129/SD-036 broker lineage requires one of two explicit SideDeck book IDs.
Choosing a book in the transport adapter would allow a caller configuration to move an
otherwise valid strategy order between the separate portfolios without changing the
signed policy digest.

## Decision

Include `book_id` in every signed SD-063 `StrategyScope`. Accept only the existing
`etoro-demo:tradingagents` and `etoro-demo:ai-trading` identifiers. Strategies in one
track must share one book so later exits can resolve ownership from durable track and
position lineage without guessing which strategy opened it. The policy digest and SD-064
grant subject therefore bind the book assignment.

SD-138 will resolve the entry's book from the signed strategy scopes and persist it in
the existing SD-036 lineage before the fake transport call. The adapter accepts only the
repository's deterministic offline eToro Demo simulator. No live transport, release or
account changes are part of this decision.

For the fake-only SD-138/139 vertical slice, every SD-064 use reference must equal the
reference passed to the typed SD-129 route. A fake full close is settled only after its
close-info reports all owned units and a separately granted/audited `/pnl` snapshot shows
exactly the four configured baseline positions with no pending or other positions. Fixture
close price is explicitly simulation-only; this path does not assert broker P&L.

## Consequences

- Policy schema v2 documents no longer parse as v3. Any future owner policy must be
  explicitly reconstructed and signed with a book assignment.
- A track cannot contain strategies assigned to different books; split those into
  separate signed policy tracks before execution.
- Historical policies and the supervised `PilotRelease` are not migrated or reused.
- This schema change does not qualify a strategy, grant execution permission or release
  `ETORO_DEMO`.
