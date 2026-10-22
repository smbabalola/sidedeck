# SD-052 MSFT instrument ID (resolved) and SD-053 pilot intent (2026-10-22)

`ETORO_DEMO_EXECUTION_RELEASE=NO_GO`, `broker_execution=DISABLED`, order transport
`NETWORK_TRANSPORT_ENABLED=False`. No order has been sent.

## SD-052 — one authorized lookup: RESOLVED_PARTIALLY_VERIFIED

| Field | Value |
|---|---|
| Authorization | Owner, 2026-10-22: one read-only MSFT search GET (second, distinct from consumed SD-050) |
| Launcher | committed `sd052_msft_lookup_cli` (`a4e9a18`, CI passed); the owner ran it locally |
| Request | exactly 1 `GET /api/v1/market-data/search?internalSymbolFull=MSFT&fields=…`, no retry, no redirect |
| Ledger | `data/sd052-auth-budget.sqlite3`: 1/1, outcome `RESOLVED_PARTIALLY_VERIFIED`; SD-052 is now in `EXHAUSTED_LOOKUP_IDS` in code |
| Lookup lock | lifted in-process only, restored in `finally` (`lookup_network_locked_after: true`) |
| **MSFT eToro instrument ID** | **1004** |
| Protected baseline conflict | **No** (4 baseline positions read-only; DB unmodified since 2026-10-20) |

Attribute verification (from `data/sd052-msft-instrument.json`):

| Attribute | Status |
|---|---|
| symbol, instrument ID | VERIFIED |
| exchange (Nasdaq) | VERIFIED |
| issuer (Microsoft) | VERIFIED |
| listing status (not delisted), visibility (not hidden) | VERIFIED |
| instrument type | **UNVERIFIED** (not returned) |
| currency | **UNVERIFIED** (not returned) |

The search `currentRate` (≈ 526.25) is an indicative value, **not** a fresh executable ask.

## Type and currency at preflight (SD-051 extension)

eToro's documented eligibility and rates responses have no dedicated instrument-type or
instrument-currency field. The preflight therefore:

* **aborts before any order** if the eligibility or rates row carries an explicit label that
  conflicts (type id ≠ 5 / non-stock name, or a currency ≠ USD / currency id ≠ 1);
* records `BROKER_VERIFIED` when such a label is present and consistent;
* otherwise records `DERIVED`: type from the required real-settlement (non-CFD) long 1×
  configuration of the Nasdaq-listed Microsoft instrument; currency from the USD eligibility
  response. The evidence label is shown in the preflight result before the owner signs the
  exact open approval, so the owner decides with the label in view.

## SD-053 — exact pilot intent (C8 schema v2), ready for the owner's signature

Generated offline by `python -m sidedeck.application.sd053_msft_pilot_intent` (idempotent;
never overwrites; re-verifies the digest).

| Field | Value |
|---|---|
| pilot_id | `64033ad7-b692-4010-bab0-0995d94e42c3` |
| broker / book | eToro Demo / `etoro-demo:tradingagents` |
| instrument | 1004 (MSFT) |
| order | buy, 1×, `limitIOC`, **0.09 units** |
| signed max limit | **552.56** (planning reference 526.25 + 5 %); 0.09 × 552.56 = **49.73 ≤ 50** |
| actual limit | derived at preflight: min(552.56, fresh realtime ask × 1.005), ask ≤ 60 s old |
| window | **Fri 2026-10-23 10:00–11:30 ET** = 14:00–15:30 UTC |
| request caps | pnl 3, eligibility 1, rates 1, open 1, lookup 3, close 1, close_info 2 = **12 (2 writes)** |
| **SHA-256 digest** | `71e111b3a8806dc9b8e59d96ce1ef6e6a0b64dc2b00363465244acccaad09a62` |

If MSFT's fresh ask on Friday exceeds 552.56, the pilot aborts before ordering (no re-sign
is attempted automatically).

### Owner signing (PowerShell), namespace `sidedeck-etoro-pilot-release`

```powershell
Set-Location "C:\Users\smbab\OneDrive\Documents\Projects\sidedeck\sidedeck"
Get-Content data\sd053-msft-pilot-intent.json
ssh-keygen -Y sign -f "$HOME\.ssh\sidedeck_approval" -n sidedeck-etoro-pilot-release data\sd053-msft-pilot-intent.digest
```

Use the key whose public half is in `data/approval_allowed_signers` (the verified key is
`sidedeck_approval`, principal `owner@sidedeck`). This writes `data\sd053-msft-pilot-intent.digest.sig`. The digest file holds the
64 hex characters with no newline.

Then, during the run, two **separate** SD-033 approvals (namespace `sidedeck-paper-approval`):
1. **Open approval** — over the exact open request the preflight derives (instrument, units,
   limit, reference id); printed by the runner after a successful preflight.
2. **Close approval** — over the exact full-close request of the lineage-verified position.

A signed release does not unlock the order transport; that requires the separate reviewed
lock-lift commit and the owner's explicit execution authorization.

## SD-054 — supervised operator runner (offline, locked)

`sidedeck.application.sd054_pilot_operator.run_pilot` composes the whole pilot: signed release
and runtime gates → desk (policy equal to the intent) → preflight → **open approval prompt**
(digest of the exact derived request; 5-minute TTL, matching the quote-age limit) → open →
**close approval prompt** → full close → final reconcile. Declining the open sends no order;
declining the close leaves the position OPEN, trips the kill-switch and reports
`UNRESOLVED_OPERATOR_INTERVENTION_REQUIRED`.

The network transport is injected (`transport_factory`), so no `src` module constructs the HTTP
order transport and `main()` refuses with `REFUSED_LOCKED` (no secret read, release not
consumed). The production factory, interactive signing prompts and
`NETWORK_TRANSPORT_ENABLED=True` ship together in one reviewed lock-lift commit, after an
independent security review and only with the owner's explicit execution authorization.
