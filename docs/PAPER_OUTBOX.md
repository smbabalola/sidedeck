# SD-12E — Durable PAPER outbox and replay (2026-10-18)

**Implementation:** \`src/sidedeck/domain/paper_outbox.py\`. This is an **offline local persistence boundary**; no Alpaca API calls, paper orders or cancellations are implemented.

- \`DurablePaperDesk\` uses a **dedicated SQLite \`.sqlite3\` file**, application marker and version; refuses to open a preexisting unrelated user database.
- \`BEGIN IMMEDIATE\` serializes local writers; \`prepare\` persists the risk-approved draft, client-order ID, correct paper key-slot and reservation together.
- \`initialize\` seeds exactly two independent USD 1,000 opening events once. No cash reset on restart.
- \`acknowledge\` stores offline broker order acknowledgment, without making or purporting to verify a broker request.
- \`reconcile_fill\` rebuilds from committed state, validates the evidence using \`SideDeckPaperDesk\`, and atomically records the local fill evidence + balanced, causally linked ledger event + cumulative order quantity/status. A replayed identical broker fill is idempotent; conflicting IDs or overfills fail closed.
- Each operation **rehydrates ledger and outstanding orders from SQLite**, rather than trusting stale process-local objects. Crash after transaction commit restores committed state; crash before commit does not persist a partial fill.
- Persistent kill switch is \`ENGAGED\`. This module exposes no way to enable broker writes. Only separate future owner-approved paper execution code may consume an order outbox, after verified distinct paper accounts and broker-native evidence/ledger mapping. **Neither this local outbox nor the existing in-memory \`SideDeckPaperDesk\` can place orders.**
- All tests use disposable local test databases under \`tmp_path\`. Neither GitHub nor CI reads private Alpaca credentials, brokerage accounts, existing user databases or stock market feeds.

**Limitations:** The current \`PaperFillEvidence\` is an injected offline contract, not authenticated Alpaca execution history. Existing \`results/demo.sqlite3\` remains separate; future production integration must unify the canonical SideDeck strategy journal and broker execution outbox under one transaction ownership and external provider verifiable identity. The new journal is an isolated paper *research* ledger, not a brokerage replacement. Account mapping is owner supplied but not yet API verified. No long-running polling or autonomous order execution is approved.

**Follow-on:** add strictly read-only Alpaca fill receipt parsers and reconciliation comparison tests, then build guarded paper write transport *code only* after durability/kill-switch and provider identity checks, without activating it. Future actual order submission requires **separate explicit user approval**.
