# SD-038 — Authorized eToro Demo baseline re-reconciliation (2026-10-21)

**Result: `MATCHED`.** All four protected baseline positions still match. There are no discrepancies, no mirror positions, no extra positions, and the baseline database is byte-identical.

**Authorization:** the owner approved a one-shot read on 2026-10-21:

- exactly 1 authenticated `GET https://public-api.etoro.com/api/v1/trading/info/demo/pnl`;
- 0 retries, 0 redirects, $0 spend.

The authorization is now **consumed and expired**.

## Safeguards applied before the request

The new runner is `src/sidedeck/application/sd038_etoro_baseline_reconcile.py`. It reuses the existing read-only `EtoroDemoReadClient` (single-path allowlist, GET only, no redirect, no retry, 15 s timeout, 5 MB cap), the strict parser and `reconcile_demo`. Before any request:

1. Demo route allowlist and client allowlist verified (`/pnl` only).
2. Baseline DB `data/etoro_demo.sqlite3` opened with SQLite `mode=ro`. Preflight found exactly 4 protected positions, 1 capture record and 0 attributions. The SHA-256 of the file bytes was recorded.
3. Only `ETORO_API_KEY`/`ETORO_USER_KEY` were loaded from the local ignored `.env` into the process. Values were never printed or persisted.
4. A persistent single-attempt budget (`data/sd038-auth-budget.sqlite3`, git-ignored, counters only) was **reserved before sending**.
5. No baseline capture, migration or database write. `--capture-baseline` is not available in this runner.

The existing CLI lacked an attempt budget and checked for the baseline only *after* its request, so a dedicated runner was added and verified offline first (16 tests).

## Sanitized result

| Field | Value |
|---|---|
| HTTP status | **200** |
| HTTP attempts consumed | **1 / 1** (budget outcome `MATCHED`) |
| Schema / field-type validation | PASSED |
| Current Demo position count | **4** |
| Protected baseline positions matched | **4 / 4** (identity, instrument, order ID, direction, units, open time) |
| Discrepancies | none (0) |
| Extra unattributed positions | 0 |
| Mirror/copy positions | none (no `mirrors[]`, no non-zero per-position `mirrorID`) |
| SideDeck-attributed positions | 0 |
| Pending orders | none |
| Baseline DB unchanged | **true** (SHA-256 identical before/after; mtime still 2026-10-20) |
| Orders / closes / modifications | 0 |
| Other endpoints contacted | none |

No credentials, account, position or order identifiers, quantities, prices, balances or raw response were printed, persisted or committed.

## What this proves, and what it does not

- **Proves:** as of 2026-10-21, the Demo account still holds exactly the four protected positions recorded on 2026-10-20, unchanged. SideDeck recognises them, attributes none of them to a strategy, and its close protection still covers them. The credentials still authenticate for Demo portfolio reads. This closes **R1**.
- **Does not prove:** that the key can or cannot write, the live order/lookup/close schemas, that a Demo transport is safe, or that capital exists for the strategy books. Execution stays `NO_GO` and `DISABLED`.

## Remaining execution-release blockers

| ID | Blocker |
|---|---|
| R2 | The owner states the key is Demo. Its Read/Write permission, IP whitelist and expiry are not independently verified (portal UI check) |
| R3 | Close recovery via `orders:lookup` is unverified (snapshot recovery exists) |
| R5 | No reviewed or released Demo write transport (SD-041 design only) |
| R6 | Live order/lookup/close response schemas are unverified (a future bounded canary is needed) |
| R8 | No capital allocated to `etoro-demo:tradingagents` / `etoro-demo:ai-trading` |
| G4 | Separate owner Demo-order release (SD-011) and supervised soak (SD-013) |

Release flags are unchanged: `ETORO_DEMO_EXECUTION_RELEASE=NO_GO`, `broker_execution=DISABLED`, `live_trading=PROHIBITED`.
