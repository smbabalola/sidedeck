# SD-129–131 — eToro Demo readiness and activation

**2026-10-27: OFFLINE ONLY. No broker call or order is authorised.**
eToro Real is permanently excluded.

## Implemented
- SD-129: typed Demo-only open, lookup, lineage and reduce-only close adapter, bound to the existing v2 order contract, with no credential or network library.
- SD-130: local credential-role preflight, never printing secrets, token lengths, account data or .env content.
- SD-131: signed nine-GET intraday data discovery draft can use the current Demo environment *names*, not only legacy aliases.

These checks do not unlock SD-107's simulator-only gateway.

## Local credential preflight (zero GETs and zero orders)

In the sidedeck-etoro-auto worktree, PowerShell:

```powershell
$env:PYTHONPATH = (Resolve-Path ".\src").Path
python -m sidedeck.application.sd130_demo_credential_preflight --env-file "..\.env"
```

Use the existing keys under names ETORO_DEMO_TRADE_API_KEY and
ETORO_DEMO_TRADE_USER_KEY. Do not also set older ETORO_API_KEY and
ETORO_USER_KEY names or inherit them from the session. Rename variable
labels locally rather than copying or publishing values or creating another
key. A local PASS does **not** verify eToro Demo read/write entitlement.

## SD-120 data discovery (owner-signed, separately authorised)

Once the owner has **actually reviewed provider terms and permitted use**,
create a zero-request unsigned scope draft:

```powershell
python -m sidedeck.application.sd120_etoro_five_minute draft `
  --out "data\sd120-current-demo-discovery-unsigned.json" `
  --owner-confirms-terms-reviewed `
  --api-key-env ETORO_DEMO_TRADE_API_KEY `
  --user-key-env ETORO_DEMO_TRADE_USER_KEY
```

A pinned owner-signed valid SD-077 grant and single-use durable ledger are
mandatory to execute the discovered scope: max nine GETs, zero retries,
exact SPY/QQQ/MSFT search, coverage and five-minute sample; no positions,
orders, portfolio access or POST. A new authorization is required; historic
pilot releases cannot be reused. The one-hour sample is 10:00–11:00 ET,
**not** enough for the 09:30 opening range or strategy backtesting. Stop
immediately if entitlement fails; do not widen scope.

## Remaining gates before automatic Demo trading

1. Licensed full-session historical and current five-minute quotes/candles,
   vetted timezones/DST, gaps, bid/ask and realistic execution friction;
   locked out-of-sample DAY strategy qualification. A fixture pass is never
   execution admission.
2. A separately reviewed *production* SD-107 Demo gateway that binds SD-129
   typed order responses to SD-063/064/074F signed spend, request and risk
   gates, persisted write-ahead intent and broker lineage. Today's SD-107
   accepts the exact offline simulator only.
3. An off-machine write-once policy/grant-use audit anchor, durable recovery,
   confirmed broker-specific exits, monitor/alerts, and protection of four
   original Demo positions. No retry after ambiguous POST; no invented closing
   price or P&L.
4. A single bounded, owner-signed DEMO-only trial release: exact instruments,
   capital, session, order/write caps and immediate HALT. Monitor supervised
   initially, and only later operate unattended if soak/reconciliation passes.

**Status:** ETORO_DEMO NOT_RELEASED; eToro Real PERMANENTLY_EXCLUDED.
