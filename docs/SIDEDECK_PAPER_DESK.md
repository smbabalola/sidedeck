# SD-12D — SideDeck paper portfolio control implementation

**Owner direction (2026-10-18):** Manage the two Alpaca paper trading portfolios from SideDeck. No additional debate on names/account provenance before progressing with offline implementation.

## Shipped code (offline scope)

- \`src/sidedeck/domain/paper_desk.py\` adds SideDeck-owned **paper limit/DAY order preparation**, preserving the two distinct strategy-to-paper-key slots: \`tradingagents → ALPACA_API_KEY\` and \`ai-trading → ALPACA_API_KEY2\`.
- A draft is accepted only after the **actual SideDeck RiskGate** approves it against the selected strategy's **real SideDeck ledger state** and mark. Enforces existing cash limits, long-only shares, 20% per-position cap, 80% exposure cap, 1% stop risk, and lack of leverage/shorts/crypto. Explicit quantity required; the preview never invokes a broker request.
- Deterministic \`client_order_id\` prevents duplicate preparation. A single unresolved order per strategy prevents overallocating cash across overlapping approvals, pending a durable reservation/outbox upgrade.
- \`acknowledge\` binds a proposed client order to one broker-side ID. \`reconcile_fill\` accepts independently verified broker fill evidence and enforces key-slot, symbol, side, broker/client IDs, quantity, non-worse limit price, fee and fill-time constraints. Each fill creates an idempotent, causally linked **SideDeck ledger posting** only in the intended strategy; duplicates do not increase cash or shares. Partial fills and closed-order overfills are explicitly handled.
- No network, credentials, broker POST/DELETE, account creation or paper order placement functions are implemented. **This does not mean Alpaca paper orders are enabled or the two real accounts have been inspected.** Separate optional read-only dual-account inspection already exists.

## Remaining work before actual paper order execution

1. Add **durable transactionally coherent order outbox/book** and idempotency recovery that persists across process crashes, maps to the existing SQL journal and refuses unintended second submissions.
2. Add hardened Alpaca paper execution transport in a separate module, default disabled and locked to paper host, with explicit one-time owner write authorisation, POST order/cancel allowlist, per-paper account verified bindings, stop/kill switch, sensible prices, error handling, and robust broker acknowledgment/partial fills. Never allow live/real brokerage APIs or any AI agent to send directly.
3. Parse *actual* Alpaca paper order/fill responses using the documented schemas and verified paper account identity. Address pending fills, bust/correction, fees, corporate actions, background polling with authorisation, and recovery. Current \`PaperFillEvidence\` is a pure contract, not proof provider supplied it.
4. Reconcile both existing Alpaca accounts, unowned positions and open orders against SideDeck's exact account/strategy mapping **before any broker write**. Preserve legacy SignalDeck positions and do not change, reset or claim them as SideDeck trades.
5. Separately implement and verify Alpaca licensed daily market-data feed, point-in-time history, training/test splits and model/data cost boundaries.

**Verification:** CI offline tests and Ruff/mypy; no connected Alpaca account/provider trading has been exercised. Maintain \`SideDeck-Blueprint/\` and user secrets. Keep draft PR unmerged.
