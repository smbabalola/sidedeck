# SD-153 Bundle R — Independent security review register

**Prepared:** 28 October 2026 · **Review state:** NOT INDEPENDENTLY REVIEWED · **Release:** NO_GO · **Transport:** eToro Demo NOT_RELEASED, eToro Real NEVER

**Verified implementation:** `84ce612e6b5bf1fe2812dac716e6dcb44c311ae3` — [exact-head CI 40667861889 PASS](https://github.com/smbabalola/sidedeck/actions/runs/40667861889): **1,943 Python passed, 2 skipped**, Ruff, mypy (206 files), Alembic, frontend and browser E2E. The first attempt `e5cba26` [CI 40667482656 FAIL](https://github.com/smbabalola/sidedeck/actions/runs/40667482656) was **test-fixture Ruff F811** only; the corrected fixture passed. No broker requests.

## Bundle R milestone 1 — read-only bounded recovery preflight

Implementation: `OfflineSwingScheduledService.recovery_read_preflight(now, max_gets=1|2)` in `src/sidedeck/application/sd152_offline_swing_runner.py`, tests `tests/test_sd153_bundle_r_recovery_preflight.py`.

- Classify each already-durable OPEN/CLOSE intent into **GET-only operator review steps**: original reference lookup, accepted-orderId lookup, close-info and/or whole-account `/pnl` snapshot (subject to its specific evidence requirements). No order submission or partial-close assumption.
- Validate **local** SD-145 audit checkpoint, policy-ledger published checkpoint, SD-064 grant ledger chain, protected four-position count and worker-fence state. Fail closed if unavailable/mismatched.
- Strict requested **planning** budget of 1–2 GETs; when exceeded, `BLOCKED_MANUAL_REVIEW`. The output **never authorises** even a planned read: `safe_to_send=false`, `automatic_get_allowed=false`, `automatic_post_allowed=false`, `clear_halt_allowed=false`, broker account unverified.
- End-to-end deterministic tests cover no-incident/empty plan, one OPEN reference, accepted CLOSE requiring two independent GETs, over-budget intents, external audit outage, invalid budget type/limits and naive clock. Every report produces **zero broker calls**. Successful tests use synthetic owner/ledger fixtures.

**Important limitations:** `max_gets` is a *planning ceiling*, not a substitute for SD-064's durable per-grant network request caps or provider rate-limit pacing. The SD-145/074 test anchors are local/off-machine-shaped fixtures, **not a deployed independently controlled remote immutable service**. There is no owner-signed operator-recovery approval, broker live authoritative read, request reservation, automatic HALT reset or service release. The preflight can never itself certify account flatness or safety to trade.

## Findings / independent reviewer requests

| ID | Priority | Review question / open work | Status |
|---|---|---|---|
| R-01 | CRITICAL release gate | Independently verify that owner-bound SD-064 grant, revocation and request caps are always rechecked immediately before every real GET/POST; test broker proxy and delayed 404/429/5xx budgets | OPEN — independent review not started |
| R-02 | CRITICAL release gate | Deploy and independently qualify off-machine immutable SD-145/074 policy, grant-use, audit, baseline and revocation evidence, including rollback/tamper tests | OPEN — requires infrastructure/owner decision |
| R-03 | HIGH | Cross-ledger recovery must use exact OPEN/CLOSE identity, units, baseline and verified broker reads, never merely a locally edited SQLite state; investigate simultaneous restarts and split fills | OFFLINE TESTED IN PART / REVIEW OPEN |
| R-04 | HIGH | Implement actual bounded GET-only retry pacing and real deadline/rate-limit errors, with no duplicate POST or automatic owner-grant renewal | OPEN — next coding slice |
| R-05 | HIGH | Define **independently signed** operator-only recovery authority and dry-run evidence packet; do not adapt a network unlock grant into a reset privilege or invent a signature | OPEN — design/approval |
| R-06 | HIGH | Verify protective exit authority after policy expiry, without automatic extension or accepting a forged/revoked grant | OFFLINE TESTED IN PART / REVIEW OPEN |
| R-07 | HIGH | Independent audit of kill-switch release, human role separation, real-vs-sim UI and no Real route | OPEN |
| R-08 | MEDIUM | Test cross-process load/restart and CI soak of negative cases and browser states in a complete operational bundle | OPEN — Bundle O |

**Acceptance for independent review closure:** named independent reviewer, reviewed commit SHA and exact signed finding decisions; remediation plus regression CI; remote ownership/provenance where required. A Codex-generated finding register, GitHub CI PASS, or a local test anchor **cannot** stand in for independent approval.

## Next Batch R work — grouped

Implement a coherent offline **bounded GET retry budget/deadline and incident plan + adversarial tests**, then an **unsigned owner-reviewable recovery evidence manifest** bound to verified policy/grant/anchor/lineage checkpoint IDs. It must not execute reads or reset HALT. Afterwards move to Bundle O's offline multi-track operations/dashboard/soak while Bundle D advances with previously permitted historical Alpaca evidence. Keep `TODO.md` up to date after each verified group.

**Owner-only matters (do not infer approval):** any authenticated Alpaca/eToro requests, remote anchor provisioning, spend, new owner grants/signatures, HALT reset and SD-150/151 Demo activation.
