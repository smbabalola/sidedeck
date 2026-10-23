# SD-058 — Monday 26 October 2026 eToro Demo MSFT pilot: owner runbook

Steering §14.1. The goal is one broker-confirmed Demo buy, fill, full close and MATCHED
reconciliation. Nothing here authorizes an order by itself.

## Pilot (fresh; never signed before)

| Field | Value |
|---|---|
| Pilot ID | `af2213c5-95c4-4207-a119-44df0ad0f78b` |
| Digest (SHA-256 of canonical intent) | `1ab4d2c8f85c94ef6fca78164b3e1e593929cc6e3cf7c52c82eae135c3d7fd4a` |
| Window | Mon 2026-10-26 **14:00–16:00 UTC** = 14:00–16:00 UK (GMT) = 10:00–12:00 New York |
| Trade | eToro Demo, book `tradingagents`, MSFT `1004`, BUY 0.09 units, 1×, limitIOC |
| Price | limit = min(552.56, fresh ask × 1.005); ≤ USD 49.73; cap USD 50 |
| Caps | 12 requests, 2 order writes, no write retries; 4 baseline positions protected |
| Last buy | 15:40 UTC (operator needs ≥ 20 min of window left to open) |

## Before 14:00 UTC

1. **Sync the PC clock** (the quote check allows only 5 s of future skew; Windows reported
   ~7.8 s dispersion on Friday). In an *administrator* PowerShell:
   `w32tm /resync` — then `w32tm /query /status` should show a recent sync.
2. **Sign the intent** (from `C:\Users\smbab\OneDrive\Documents\Projects\sidedeck\sidedeck`):

   ```powershell
   $digestFile = "data\sd053-msft-pilot-intent-20261026-v2.digest"
   if ((Get-Content $digestFile -Raw).Trim() -ne "1ab4d2c8f85c94ef6fca78164b3e1e593929cc6e3cf7c52c82eae135c3d7fd4a") { throw "Digest mismatch - STOP" }
   ssh-keygen -Y sign -f "$HOME\.ssh\sidedeck_approval" -n sidedeck-etoro-pilot-release $digestFile
   .\.venv\Scripts\python.exe -m sidedeck.application.sd054_pilot_operator verify
   ```

   Expect `signature_valid: true` and the full digest above.
3. **Send Claude, in your own words:** acceptance of `NAIVE_AS_UTC` for this single pilot and
   approval of the lock-lift for `1ab4d2c8f85c94ef6fca78164b3e1e593929cc6e3cf7c52c82eae135c3d7fd4a`.
   Claude applies only this change, tests, commits, pushes, confirms exact-HEAD CI and
   returns READY_FOR_OWNER_RUN:

   ```diff
   -UNLOCKED_PILOT_DIGEST: str | None = None
   +UNLOCKED_PILOT_DIGEST: str | None = (
   +    "1ab4d2c8f85c94ef6fca78164b3e1e593929cc6e3cf7c52c82eae135c3d7fd4a")
   ```
   (`NETWORK_TRANSPORT_ENABLED` stays `False`; every other digest stays locked.)

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

## Known risk: quote freshness

Friday's last attempt was rejected `stale or future-dated` (age not recorded then; now it is).
An earlier quote was ~30 s old on arrival. The 60 s / 5 s limits are kept. If Monday is
rejected again, the report states the exact age and whether it was stale or future-dated.
