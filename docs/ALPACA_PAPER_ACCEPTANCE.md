# Alpaca PAPER acceptance handoff — local Codex only

**2026-10-18.** SideDeck read-only Alpaca paper integration is source/test verified, NOT authenticated/provider verified. Alpaca is the intended *paper* broker; SideDeck is the only portfolio dashboard, risk and ledger control plane. No real orders, no live brokerage host, no eToro. The existing eToro probe permission is exhausted.

## Offline checks (no network; proceed without asking)

1. Safely sync `feat/p2-agent-adapters`, preserving ignored `.env`, local databases, `SideDeck-Blueprint/` and any untracked work. **No auto-merge or reset.**
2. Read `docs/ADR-002-alpaca-paper-control-plane.md`; verify local `ALPACA_API_KEY` is present and nonempty. Also check for the **paired paper secret** in `ALPACA_SECRET_KEY`, `ALPACA_API_SECRET_KEY` or `APCA_API_SECRET_KEY`. Report only boolean presence and whether aliases conflict. Do not read/print/hash prefixes, values, lengths, account IDs or secret-bearing errors into output, logs or GitHub.
3. Confirm through existing *local* documentation/configuration evidence that the key pair belongs to Alpaca **Paper** rather than Live. If this cannot be confirmed offline, label `PAPER_KEY_SCOPE_UNVERIFIED` and request the owner to inspect the Alpaca dashboard. Never test keys against the real brokerage host.
4. In the local SideDeck venv run `PYTHONPATH=src python -m sidedeck.paper --dry-run`, offline pytest/Ruff/mypy as needed. Confirm `FIXTURE_NOT_REAL`, synthetic `1000`, zero external HTTP requests. A fixture's account/positions is never a provider-authentication pass.

## Bounded paper read-only verification (requires deliberate owner opt-in)

Only after account scope and credentials are verified locally and owner confirms a one-time read-only inspection, load `.env` **into the child process only** without printing it. Run exactly once in the SideDeck checkout:

```powershell
$env:PYTHONPATH = "src"
.venv\Scripts\python.exe -m sidedeck.paper --paper-only --allow-read-network --confirm-owner-paper-read-only
```

The CLI makes exactly three GETs to **`https://paper-api.alpaca.markets`**: `/v2/account`, `/v2/positions`, `/v2/orders?status=open&limit=100`. No retries; fail closed if blocked, malformed, unapproved symbols or shorts. **Never POST, DELETE, cancel, reset, fund or place an order**, never contact eToro, Yahoo, paid feeds, or live brokerage services. No account ID/key/secret in output; the local report can show personal cash/equity/positions to the owner, but do not push these amounts into public GitHub.

Record in `TODO.md` only status booleans, denied HTTP status, blocked account restrictions, missing secret-variable name or safe error category. If status non-200, stop. Even if 200, this does not authorize paper trades, prove independence of two broker accounts, or make SideDeck's research AI engines fully operational.

## Portfolio mapping and order acceptance (future, separate approval)

1. Confirm whether owner has **two distinct Alpaca paper accounts**. If only one, preserve independent SideDeck `tradingagents` and `ai-trading` USD 1000 simulated ledgers; broker paper execution remains disabled. Owner may create a second paper account in Alpaca dashboard and provision separately named secrets, never in GitHub.
2. Build SideDeck-controlled portfolio manager with per-strategy broker mapping, risk validation, no short/leverage/crypto/CFD/options, idempotent `client_order_id`, kill switch, order/fill recovery and broker/ledger reconciliation.
3. Require a **new explicit permission for Alpaca PAPER writes** only after two broker accounts, attribution and actual read-only acceptance. No auto-start. All control remains from SideDeck.
4. Separately authorize/verify Alpaca's historical data API, NYSE/Nasdaq calendar, five-year adjusted daily OHLCV, data usage rights and vintage. Existing fixture portfolio dashboard must stay labelled synthetic.

**Security:** provider domain allowlist and private `.env` are not evidence of paper-key provenance; neither the current integration nor unit tests can verify credentials. The owner must never share secrets in chat.

## Confirmed by owner; requires local provider verification (2026-10-18)

Owner reports first paper-account label **signaldeckdemo** linked to `ALPACA_API_KEY`, and second **Sidedeckdemo** linked to `ALPACA_API_KEY2`. Strategy mapping is provisionally `tradingagents`/first key and `ai-trading`/second key. Do not assume the first owner label equals screenshot's **SignalDeckProject** until verified against the provider's distinct account IDs privately. Before even considering PAPER orders, confirm neither account carries activity from another app/experiment, especially the original SignalDeck system. Existing broker cash (often USD 100,000) is not either SideDeck USD 1,000 ledger. Current permission is to document the mapping only, **not to authenticate against Alpaca or place any order**.
