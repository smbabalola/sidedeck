# SD-057 — Consolidated release request: first eToro Demo MSFT trade

**Status: DRAFT — not yet presentable.** Prerequisites outstanding: the owner's SSH signature
over the pinned intent (SD-055) and closure of the independent transport review (SD-056).
This document is **not** an authorization. `ETORO_DEMO_EXECUTION_RELEASE=NO_GO`,
`broker_execution=DISABLED`, `NETWORK_TRANSPORT_ENABLED=False`.

## What the owner would be releasing

| Item | Value |
|---|---|
| Broker / environment | eToro **Demo** only, host `https://public-api.etoro.com`; eToro Real routes refused before I/O (permanent) |
| Account scope | the owner's single Demo account via the owner-accepted Demo key pair (ADR-004); book `etoro-demo:tradingagents` |
| Instrument | Microsoft, eToro instrument **1004** (SD-052; exchange and issuer verified; type/currency checked at preflight) |
| Order | **BUY 0.09 units**, leverage **1×**, `limitIOC`, `orderCurrency=usd` |
| Limit | min(**552.56**, fresh realtime ask × 1.005), ask ≤ 60 s old; abort if the ask exceeds 552.56 |
| Maximum notional | **USD 50** signed cap (0.09 × 552.56 = 49.73) |
| Window / expiry | **Fri 2026-10-23 10:00–11:30 ET** (14:00–15:30 UTC); release unusable outside it; never rolled forward |
| Pilot intent digest | `71e111b3a8806dc9b8e59d96ce1ef6e6a0b64dc2b00363465244acccaad09a62` (pilot id `64033ad7-b692-4010-bab0-0995d94e42c3`) |
| Signed-release verification | *pending SD-055* — `python -m sidedeck.application.sd054_pilot_operator verify` |

### Authenticated endpoint allowlist and budget (12 requests, 2 writes)

| # | Method and path | Purpose | Cap |
|---|---|---|---|
| 1 | GET `/api/v1/trading/info/demo/pnl` | baseline before, after open, final | 3 |
| 2 | POST `/api/v2/trading/info/demo/eligibility` (body pinned: `{instrumentIds:[1004], currency:USD}`) | read-only eligibility | 1 |
| 3 | GET `/api/v2/market-data/rates?instrumentIds=1004` | fresh realtime ask | 1 |
| 4 | POST `/api/v2/trading/execution/demo/orders` (body pinned to the signed intent) | **open — write** | **1** |
| 5 | GET `/api/v2/trading/info/demo/orders:lookup?referenceId=…` | open outcome / lineage | 3 |
| 6 | POST `/api/v1/trading/execution/demo/market-close-orders/positions/{SideDeck positionId}` (`UnitsToDeduct: null`) | **full close — write** | **1** |
| 7 | GET `/api/v1/trading/info/demo/close-orders/{orderId}` | close outcome | 2 |

Caps are enforced three times (signed intent caps, transport ledger per release digest, pilot
budget). No write retries; `x-request-id` = reference id; no redirects; proxies ignored.

### Invariants and controls

* **Protected baseline:** the 4 pre-existing Demo positions must reconcile MATCHED before the
  open and at the end; any baseline position is refused as a target; ownership only through
  referenceId → orderId → positionId lineage.
* **Approvals:** open and close each need a separate owner signature (`sidedeck-paper-approval`)
  over the exact request digest; open approval TTL 5 min (quote freshness), close 30 min.
* **Kill-switch / recovery:** any unknown acknowledgement, lost response, non-terminal or
  inconsistent outcome, declined or failed close → `UNRESOLVED_OPERATOR_INTERVENTION_REQUIRED`,
  kill-switch tripped, true state retained; recovery is lookup-only, never a resubmission.
* **COMPLETE** only when the close is FILLED, the final reconcile is MATCHED and zero SideDeck
  positions remain.

## Steps after the owner's release

1. Reviewed lock-lift commit (sets `NETWORK_TRANSPORT_ENABLED = True`; nothing else), CI green.
2. Inside the window the owner runs (host safety prevents Claude from doing so):
   ```powershell
   Set-Location "C:\Users\smbab\OneDrive\Documents\Projects\sidedeck\sidedeck"; .\.venv\Scripts\python.exe -m sidedeck.application.sd054_pilot_operator run --confirm-owner-release
   ```
   and signs the printed open (then close) digest in a second PowerShell window:
   `ssh-keygen -Y sign -f "$HOME\.ssh\sidedeck_approval" -n sidedeck-paper-approval "<printed digest file>"`.
3. Immediately after: lock re-engaged by a follow-up commit; report, accounting and audit
   recorded (SD-062).
