# SD-058 — Tuesday 27 October 2026 eToro Demo MSFT pilot: owner runbook (Monday 1ab4d2c8 consumed: stale quote)

Steering §14.1. The goal is one broker-confirmed Demo buy, fill, full close and MATCHED
reconciliation. Nothing here authorizes an order by itself. This is the **only** current
operational document; `SD057_FIRST_DEMO_TRADE_RELEASE_REQUEST.md` is historical.

## GO / NO-GO checklist (all must be GO, in order)

| # | Gate | GO when | Who |
|---|---|---|---|
| 1 | Code frozen | HEAD contains no change to intent, digest, operator pin or risk limits since `5ad3d94`; exact-HEAD CI green | Claude |
| 2 | Clock | `w32tm /resync` succeeded; `w32tm /query /status` shows a sync within the last few minutes | Owner |
| 3 | Intent | `.digest` file equals `40ee9682e44ff773da25849701a50caa098e94e5601450d9c46a5c7a2d2a69cb` (script below throws otherwise) | Owner |
| 4 | Signature | `verify` → `signature_valid: true`, `release_consumed: false`, `requests_sent: 0` | Owner + Claude |
| 5 | Account / baseline | Demo credentials only; recorded baseline MATCHED with the four protected positions (checked by preflight; any mismatch aborts before a write) | Operator |
| 6 | Kill switch | CLEAR (no unresolved prior pilot) | Claude (offline read) |
| 7 | Window | Now ≥ 14:00 UTC and ≤ 15:40 UTC (operator refuses to open with < 20 min left) | Owner |
| 8 | Owner acceptance | Owner's own message: `NAIVE_AS_UTC` for this pilot + lock-lift approval for the full digest | Owner |
| 9 | Lock-lift | Only `UNLOCKED_PILOT_DIGEST` changed; exact-HEAD CI green → READY_FOR_OWNER_RUN | Claude |
| 10 | Buy approval | Signed in the SECOND window **within ~4½ min** of the prompt (open approval and quote both expire after 5 min) | Owner |
| 11 | Close approval | Signed promptly after the fill (approval valid ≤ 30 min, never beyond 16:00 UTC) | Owner |
| 12 | Re-lock | `UNLOCKED_PILOT_DIGEST = None` committed and CI green, whatever the outcome | Claude |

Any NO-GO → stop; no broker request is sent before gate 9, and nothing is retried.

## Pilot (fresh; never signed before)

| Field | Value |
|---|---|
| Pilot ID | `e4512119-13cc-4900-aab1-cab8e67c801b` |
| Digest (SHA-256 of canonical intent) | `40ee9682e44ff773da25849701a50caa098e94e5601450d9c46a5c7a2d2a69cb` |
| Window | Tue 2026-10-27 **14:00–16:00 UTC** = 14:00–16:00 UK (GMT) = 10:00–12:00 New York |
| Trade | eToro Demo, book `tradingagents`, MSFT `1004`, BUY 0.09 units, 1×, limitIOC |
| Price | limit = min(552.56, fresh ask × 1.005); ≤ USD 49.73; cap USD 50 |
| Caps | 15 requests (signed, enforced at runtime), incl. up to 4 quote reads ~15 s apart only while the quote is stale; 2 order writes, no write retries; 4 baseline positions protected |
| Last buy | 15:40 UTC (operator needs ≥ 20 min of window left to open) |

## Before 14:00 UTC

1. **Sync the PC clock** (the quote check allows only 5 s of future skew; Windows reported
   ~7.8 s dispersion on Friday). In an *administrator* PowerShell:
   `w32tm /resync` — then `w32tm /query /status` should show a recent sync.
2. **Sign the intent** (from `C:\Users\smbab\OneDrive\Documents\Projects\sidedeck\sidedeck`):

   ```powershell
   $digestFile = "data\sd053-msft-pilot-intent-20261027.digest"
   if ((Get-Content $digestFile -Raw).Trim() -ne "40ee9682e44ff773da25849701a50caa098e94e5601450d9c46a5c7a2d2a69cb") { throw "Digest mismatch - STOP" }
   ssh-keygen -Y sign -f "$HOME\.ssh\sidedeck_approval" -n sidedeck-etoro-pilot-release $digestFile
   .\.venv\Scripts\python.exe -m sidedeck.application.sd054_pilot_operator verify
   ```

   Expect `signature_valid: true` and the full digest above.
3. **Send Claude, in your own words:** acceptance of `NAIVE_AS_UTC` for this single pilot and
   approval of the lock-lift for `40ee9682e44ff773da25849701a50caa098e94e5601450d9c46a5c7a2d2a69cb`.
   Claude applies only this change, tests, commits, pushes, confirms exact-HEAD CI and
   returns READY_FOR_OWNER_RUN:

   ```diff
   -UNLOCKED_PILOT_DIGEST: str | None = None
   +UNLOCKED_PILOT_DIGEST: str | None = (
   +    "40ee9682e44ff773da25849701a50caa098e94e5601450d9c46a5c7a2d2a69cb")
   ```
   (`NETWORK_TRANSPORT_ENABLED` stays `False`; every other digest stays locked.)

   **Freeze:** after `9b9da1a` no change may touch the intent, digest, operator pin, request
   caps, price or freshness limits before the run; only docs/tests are allowed.

## The run (after READY_FOR_OWNER_RUN, inside the window)

```powershell
.\.venv\Scripts\python.exe -m sidedeck.application.sd054_pilot_operator run --confirm-owner-release
```

At **each** approval (buy, then close):

1. Leave this FIRST window running.
2. Open a SECOND PowerShell window, `cd` to the same folder, paste the `sign_in_powershell`
   command it printed, enter the passphrase, wait for `Write signature to ...`.
3. Return to the FIRST window and press Enter. (An early Enter now re-prompts; `NO` declines.)

Sign the close promptly — declining it leaves the position open and trips the kill switch.

## After the run

Paste the full output to Claude. Claude re-locks immediately, preserves evidence and
reconciles. COMPLETE only when broker records show open fill, close fill, zero pilot position,
MATCHED reconciliation, unchanged baseline and transport re-locked.

| Outcome | What the report shows | Response |
|---|---|---|
| **A — success** | `result: COMPLETE`; open step `OPEN_FILLED_AWAITING_CLOSE_APPROVAL` with broker `entry`; close step FILLED, 0 SideDeck positions, kill switch CLEAR | Re-lock; verify fills, flat position, MATCHED, baseline unchanged from the saved evidence; mark SD-058 COMPLETE |
| **B — rejected before opening** | `ABORTED_PREFLIGHT` / `ABORTED_OPEN_NOT_APPROVED` / `ABORTED_WINDOW_TOO_SHORT`; 0 writes | Re-lock; no retry. Read the audit (quote age with sign: negative = future-dated; time basis; timestamp shape); diagnose before any new pilot |
| **C — bought, close unresolved** | `UNRESOLVED_OPERATOR_INTERVENTION_REQUIRED`, position may be OPEN, kill switch tripped | Re-lock; do **not** rerun or close manually by script. SideDeck never resubmits a close; read lineage + audit offline; check the Demo position in the eToro UI; owner directs recovery |


## Known risk: quote freshness

Friday's last attempt was rejected `stale or future-dated` (age not recorded then; now it is).
An earlier quote was ~30 s old on arrival. The 60 s / 5 s limits are kept. If Monday is
rejected again, the report states the exact age and whether it was stale or future-dated.
