# SD-12I — SideDeck guarded paper dispatcher (unreleased)

The **GuardedPaperDispatcher** wires the two existing private paper credential
pairs to their corresponding GET account inspectors and the existing locked
Alpaca **paper-only** POST transport. It is NOT imported by the application
entrypoint, has no UI/CLI launch command, and its global write gate is
**`NETWORK_PAPER_WRITES_ENABLED=False`**. No actual broker request has run.

A future owner-authorized dispatch must have a fresh signed-off order, exact
SideDeck `client_order_id` and key slot, short-lived permit, two distinct
active unblocked Alpaca paper accounts validated by the **same credential pairs**
as used for POST, and a committed `UNCERTAIN` durable claim **before** the
single POST. The order can only be acknowledged after the returned paper
order UUID, quantity, symbol, price, side, type, and duration match the
accepted SideDeck draft.

Timeout, HTTP denial and malformed responses all leave UNCERTAIN: the
dispatcher NEVER resends a POST. A read-only recovery function can check
the original client ID even after the order's quote and initial permit
expire. A 404/403 during recovery does not make retry safe.

The current `KEY_SLOT_CHECKED` marker is *not a verified broker account ID
fingerprint*. Without durable provider-bound account attestation and
acceptance of fees/corrections/real data, production execution must remain
disabled. Margin/buying-power from the paper broker never overrides SideDeck's
USD 1000 simulated allocation.

All tests monkeypatch the read-only transport and HTTP sender, using synthetic
credentials. Tests with `NETWORK_PAPER_WRITES_ENABLED=True` do so only
inside mocked CI; no real network or account mutation occurs. Never toggle
this flag in a user runtime, and never print or push credentials.

Next: account preflight with provider identity durable attestation, source
data checks, human-reviewed per-order action, release procedure and actual
local read-only acceptance. **Do not submit paper orders until the owner
explicitly approves the first bounded live-paper order and both account
IDs have been checked locally.** Real trading remains prohibited.

## Verified code result

`7441e7a1fe13446ec71c5e7505eab336a596384e`: 269 offline tests passed, Ruff/mypy (40 source files) clean, PostgreSQL CI green. See https://github.com/smbabalola/sidedeck/actions/runs/39203827920 .

### User-local next acceptance, no brokerage mutation

In the existing SideDeck checkout, preserve ignored `.env`, `.venv`, user database files, `SideDeck-Blueprint/`, and any untracked work. Local Codex should first run offline tests and confirm **presence only** of both `ALPACA_API_KEY` and `ALPACA_API_KEY2` plus their matching paper secrets. It must not output values, hashes, lengths or account IDs.

Once owner authorizes the read-only account check, use `sidedeck.paper_pair` with its explicit permission flags to GET **one account identity per key pair**. Report distinctness, status, restrictions and any safe HTTP error category, not financial or private identifiers. It does not place orders. **Do not** run `GuardedPaperDispatcher.dispatch` or flip the write gate; paper execution remains disabled until provider acceptance, market-data proof and separate bounded owner permission. Do not publish secrets or trade history.
