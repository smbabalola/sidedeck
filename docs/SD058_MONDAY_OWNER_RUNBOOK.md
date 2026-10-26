# SD-058 — Monday 26 October 2026 (afternoon) eToro Demo MSFT pilot: owner runbook (morning 1ab4d2c8 consumed: stale quote; Tuesday 40ee9682 signed but superseded, preserved)

Steering §14.1. The goal is one broker-confirmed Demo buy, fill, full close and MATCHED
reconciliation. Nothing here authorizes an order by itself. This is the **only** current
operational document; `SD057_FIRST_DEMO_TRADE_RELEASE_REQUEST.md` is historical.

## GO / NO-GO checklist (all must be GO, in order)

| # | Gate | GO when | Who |
|---|---|---|---|
| 1 | Code frozen | HEAD contains no change to intent, digest, operator pin or risk limits since the `4119f25c…` pin commit (Option B code `a7590e6`); exact-HEAD CI green | Claude |
| 2 | Clock | `w32tm /resync` succeeded; `w32tm /query /status` shows a sync within the last few minutes | Owner |
| 3 | Intent | `.digest` file equals `4119f25c82ea64042f9126275e69b45ca79edda70c181eb361c9c69b8671b7dd` (script below throws otherwise) | Owner |
| 4 | Signature | `verify` → `signature_valid: true`, `release_consumed: false`, `requests_sent: 0` | Owner + Claude |
| 5 | Account / baseline | Demo credentials only; recorded baseline MATCHED with the four protected positions (checked by preflight; any mismatch aborts before a write) | Operator |
| 6 | Kill switch | CLEAR (no unresolved prior pilot) | Claude (offline read) |
| 7 | Window | Now ≥ 15:30 UTC and ≤ 19:10 UTC (operator refuses to open with < 20 min left) | Owner |
| 8 | Owner acceptance | Owner's own message: `NAIVE_AS_UTC` for this pilot + lock-lift approval for the full digest | Owner |
| 9 | Lock-lift | Only `UNLOCKED_PILOT_DIGEST` changed; exact-HEAD CI green → READY_FOR_OWNER_RUN | Claude |
| 10 | Buy approval | Signed in the SECOND window **within ~4½ min** of the prompt (open approval and quote both expire after 5 min) | Owner |
| 11 | Close approval | Signed promptly after the fill (approval valid ≤ 30 min, never beyond 19:30 UTC) | Owner |
| 12 | Re-lock | `UNLOCKED_PILOT_DIGEST = None` committed and CI green, whatever the outcome | Claude |

Any NO-GO → stop; no broker request is sent before gate 9, and nothing is retried.

## Pilot (fresh; never signed before)

The Tuesday intent `e4512119…` / `40ee9682…` (file `sd053-msft-pilot-intent-20261027.*`,
signed 2026-10-26 15:19) is preserved untouched. It is no longer pinned, so it cannot run;
it could only be reinstated by a separate reviewed change. Its signature cannot authorise
today's digest.

| Field | Value |
|---|---|
| Pilot ID | `e7987485-3a97-477e-9343-576ce62ce2ff` |
| Digest (SHA-256 of canonical intent) | `4119f25c82ea64042f9126275e69b45ca79edda70c181eb361c9c69b8671b7dd` |
| Window | **Mon 2026-10-26 15:30–19:30 UTC** = 15:30–19:30 UK (GMT) = 11:30–15:30 New York (US close 20:00 UTC) |
| Trade | eToro Demo, book `tradingagents`, MSFT `1004`, BUY 0.09 units, 1×, limitIOC |
| Price | limit = min(552.56, fresh ask × 1.005); ≤ USD 49.73; cap USD 50 |
| Caps | 15 requests (signed, enforced at runtime), incl. up to 4 quote reads ~15 s apart only while the quote is stale; 2 order writes, no write retries; 4 baseline positions protected |
| Last buy | 19:10 UTC (operator needs ≥ 20 min of window left to open) |

## Before the run (window already open from 15:30 UTC)

1. **Sync the PC clock** (the quote check allows only 5 s of future skew; Windows reported
   ~7.8 s dispersion on Friday). In an *administrator* PowerShell:
   `w32tm /resync` — then `w32tm /query /status` should show a recent sync.
2. **Sign the intent** (from `C:\Users\smbab\OneDrive\Documents\Projects\sidedeck\sidedeck`):

   ```powershell
   $digestFile = "data\sd053-msft-pilot-intent-20261026-optb.digest"
   if ((Get-Content $digestFile -Raw).Trim() -ne "4119f25c82ea64042f9126275e69b45ca79edda70c181eb361c9c69b8671b7dd") { throw "Digest mismatch - STOP" }
   ssh-keygen -Y sign -f "$HOME\.ssh\sidedeck_approval" -n sidedeck-etoro-pilot-release $digestFile
   .\.venv\Scripts\python.exe -m sidedeck.application.sd054_pilot_operator verify
   ```

   Expect `signature_valid: true` and the full digest above.
3. **Send Claude, in your own words:** acceptance of `NAIVE_AS_UTC` for this single pilot and
   approval of the lock-lift for `4119f25c82ea64042f9126275e69b45ca79edda70c181eb361c9c69b8671b7dd`.
   Claude applies only this change, tests, commits, pushes, confirms exact-HEAD CI and
   returns READY_FOR_OWNER_RUN:

   ```diff
   -UNLOCKED_PILOT_DIGEST: str | None = None
   +UNLOCKED_PILOT_DIGEST: str | None = (
   +    "4119f25c82ea64042f9126275e69b45ca79edda70c181eb361c9c69b8671b7dd")
   ```
   (`NETWORK_TRANSPORT_ENABLED` stays `False`; every other digest stays locked.)

   **Freeze:** after the commit that pins `4119f25c…` no change may touch the intent, digest, operator pin, request
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
