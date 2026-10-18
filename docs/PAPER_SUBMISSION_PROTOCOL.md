# SD-12G — Alpaca PAPER submission protocol (fixture gated)

The owner instructed us to continue engineering controlled Alpaca paper-order
submission. **No actual Alpaca paper or live orders are authorized by this coding
run.** This milestone implements dispatch/recovery contracts and tests without
any production-capable POST transport, credential loading, or broker network calls.

## Safety design

- SideDeck owns and risk-approves exact LIMIT/DAY orders, keeps USD 1,000
  separate ledgers, deterministic \`client_order_id\` and owner-reported
  \`ALPACA_API_KEY\` / \`ALPACA_API_KEY2\` strategy routing.
- Every proposal must still be fresh (≤60 seconds), with its local reserved
  order, correct key slot and no prior broker acknowledgment. The injected
  read-only account check must find **two distinct active unblocked paper
  accounts**. One additional key on the same account is not enough.
- \`DurablePaperDesk.stage_paper_submission\` persistently claims **one**
  potential dispatch attempt as \`UNCERTAIN\` before any external operation.
  A returned 201 with a fully verified client-order/UUID/limit/day/quantity
  acceptance is recorded as \`ACKNOWLEDGED\`. Both persist over restarts.
- **Timeout, 5xx, response ambiguity and crash = UNCERTAIN**. A second POST
  is forbidden, even after restart. Recovery is by **GET order by
  client_order_id** only, with independently validated broker identity and
  fresh paper credentials, before any new write attempt.
- The persistent kill switch is \`ENGAGED\` and cannot be disabled by these
  methods. \`SideDeckPaperSubmission.submit_fixture_once\` accepts only an
  explicitly marked \`fixture_only=True\` injected writer, not a real HTTP
  transport. The returned count of actual broker orders/network calls is 0.
- **No production Alpaca order POST implementation or executable CLI is
  included.** Real broker request enablement requires fresh user approval
  plus verified paper-account binding, real-market data freshness, an
  account-specific revocable write permit, accurate broker-sourced fees and
  fill corrections, production HTTP error handling, and supervised acceptance.
- The stored \`OFFLINE_FIXTURE:portfolio\` marker is not a broker account ID and
  never represents validated real broker identity. All fixture acknowledgments
  must stay in disposable test databases.

## Next integration

Build a **paper-only HTTP submission transport** as an isolated, default-off
component with zero real-money host support. Validate its request construction
against Alpaca's API and mock it in CI. Do not make an authenticated HTTP POST
or load owner credentials until there is express approval for a bounded paper
order. Add durable account ID binding and a full reconciliation-read chain
before enabling any production worker, even if the paper environment has
USD 100,000 cash.

Sources:
- https://docs.alpaca.markets/us/reference/postorder
- https://docs.alpaca.markets/us/reference/getorderbyclientorderid
- https://docs.alpaca.markets/us/docs/working-with-orders
