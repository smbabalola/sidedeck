# SD-057 — Consolidated release request: first eToro Demo MSFT trade

**Status: READY FOR THE OWNER'S DECISION (2026-10-22).** All offline prerequisites pass.
This document is **not** an authorization. `ETORO_DEMO_EXECUTION_RELEASE=NO_GO`,
`broker_execution=DISABLED`, `NETWORK_TRANSPORT_ENABLED=False`, `UNLOCKED_PILOT_DIGEST=None`.

## Verified evidence

| Check | Result |
|---|---|
| Owner release signature (SD-055) | **VALID** — SideDeck verifier `signature_valid: true`; independent `ssh-keygen -Y verify`: `Good "sidedeck-etoro-pilot-release" signature for owner@sidedeck with ED25519 key SHA256:7qb8dAz9c2/1X4jb+qlqI3O91Xfc3jbSmfNvrW3/rUI` |
| Signed bytes | SHA-256(canonical intent) = digest file = pinned `71e111b3…9a62`; intent files unmodified since 2026-10-22 16:19 local; re-derived from code parameters on load |
| Signer | `data/approval_allowed_signers` holds exactly the pinned key (SHA-256 of blob `600a7f7e…0f3`) |
| Release state | not consumed (`data/sd054/` absent), 0 requests sent |
| Instrument | MSFT = 1004 (SD-052), no protected-baseline conflict |
| Independent security review (SD-056) | 0 critical / 0 high; all medium + actionable low findings fixed with tests |
| Regression | 903 passed, 1 skipped; Ruff, mypy, Alembic, web build clean; exact-HEAD CI green |
| Lock-lift simulation | full suite passes with `UNLOCKED_PILOT_DIGEST` set to the pilot digest in memory and sockets blocked |

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
* **Approvals:** open and close each need a separate owner signature (`sidedeck-etoro-pilot-approval`)
  over the exact request digest; open approval TTL 5 min (quote freshness); close TTL 30 min clipped to the window end; the open is refused unless ≥ 20 min of the signed window remain; signer key pinned (SHA-256 `600a7f7e…0f3`).
* **Kill-switch / recovery:** any unknown acknowledgement, lost response, non-terminal or
  inconsistent outcome, declined or failed close → `UNRESOLVED_OPERATOR_INTERVENTION_REQUIRED`,
  kill-switch tripped, true state retained; recovery is lookup-only, never a resubmission.
* **COMPLETE** only when the close is FILLED, the final reconcile is MATCHED and zero SideDeck
  positions remain.

## Steps after the owner's release

1. Reviewed one-line lock-lift commit: `UNLOCKED_PILOT_DIGEST = "71e111b3a8806dc9b8e59d96ce1ef6e6a0b64dc2b00363465244acccaad09a62"`
   (global `NETWORK_TRANSPORT_ENABLED` stays False). Only this signed release can open a
   network transport, and every request still requires the signed window; CI green.
2. Inside the window the owner runs (host safety prevents Claude from doing so):
   ```powershell
   Set-Location "C:\Users\smbab\OneDrive\Documents\Projects\sidedeck\sidedeck"; .\.venv\Scripts\python.exe -m sidedeck.application.sd054_pilot_operator run --confirm-owner-release
   ```
   and signs each printed open (then close) approval in a second PowerShell window using the
   exact `sign_in_powershell` command the runner prints: it re-checks the digest file against
   the on-screen digest before signing (namespace `sidedeck-etoro-pilot-approval`).
3. Immediately after (or at 11:30 ET, whichever is first): `UNLOCKED_PILOT_DIGEST = None` re-lock commit; report, accounting and audit
   recorded (SD-062).
