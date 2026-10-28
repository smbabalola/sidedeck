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

## Bundle R milestone 2 — durable GET retry fence and unsigned evidence manifest

**Verified code/test `7094ced7e0e31f752fbdfb39f02538641b879a9b`: [exact-head CI 40670056735 PASS](https://github.com/smbabalola/sidedeck/actions/runs/40670056735): 1,949 passed / 2 skipped**, Ruff, mypy (206 files), migrations, frontend and browser E2E. Preceding durable GET stage tests `d5f84c8` passed [CI 40669322876](https://github.com/smbabalola/sidedeck/actions/runs/40669322876) (1,946 / 2); subsequent replay-aware read-only preflight `bd57a65` passed [CI 40669476872](https://github.com/smbabalola/sidedeck/actions/runs/40669476872) (1,947 / 2).

- **Durable GET stage budget:** SD-036 adds `etoro_demo_offline_recovery_reads` with a unique `(order_reference,stage)` under SQLite `BEGIN IMMEDIATE`. The SD-138 fake `recover_entry` flow now reserves the `REFERENCE` attempt before the broker-shaped GET. A fallback by **saved, validated accepted order ID only**, after the first GET's simulated 404, must separately reserve `ACCEPTED_ORDER_ID` within 120 seconds of the first stage. Any clock regression, late fallback, repeated stage or process restart replay fails closed: **no third GET and never another POST**. Stages persist across separate SD-036 handles; reservation is deliberately consumed if a process crashes before reaching the fake transport.
- **Gate remains separate:** each attempted read still passes SD-064 owner-signed grant checks and SD-145 audit append before its reservation/transport; a consumed grant on subsequent denied replay is conservative, not an authority bypass. This **offline** reservation alone cannot authorize a real GET; network transport remains unavailable. It intentionally does **not** yet provide production 429/5xx backoff or rate-limit pacing.
- **Preflight reflects actual retries:** SD-152 `recovery_read_preflight` now blocks any suggested repeated OPEN GET when a durable recovery stage is already reserved; status `BLOCKED_MANUAL_REVIEW` replaces a misleading repeat suggestion.
- **Unsigned manifest:** SD-152 `recovery_evidence_manifest` fingerprints canonical local policy ID/digest, policy/grant/audit checkpoint heads, local protected original baseline facts, complete durable order/owned-position snapshot and the non-executable recovery plan. It is repeatable for the same unmodified local evidence; changing a read reservation changes the digest. On missing audit checkpoint it returns `UNRESOLVED`. **It does not attest authentic broker holdings or an immutable remote anchor, does not sign for the owner, and cannot reset HALT or send anything.**
- **Negative evidence:** tests cover two 404s, restart after exhaustion, 121-second fallback denial, backward clock, duplicate reservation from a second DB handle, preflight replay refusal, manifest digest change and anchor outage. None accesses credentials, uses the real eToro API, resets the kill switch or places an order.

**Still open:** independent owner-authenticated broker baseline, deployed true remote immutable anchor, authenticated operator-signed recovery decisions, actual provider GET retry-after/429/5xx pacing, independent security review and any SD-150/151 Demo release. **Bundle R remains IN_PROGRESS**, not ready for a broker canary.

## Bundle R milestone 3 — bounded transient GET retries and local signed review

**Verified offline implementation:** `sd138_autonomous_order_adapter.py` retries only fake recovery GET statuses 429/500/502/503/504, with a numeric `Retry-After` in `(0,30]`, at most three attempts, and a 120-second stage deadline. Every retry obtains a fresh SD-064 grant use, appends audit evidence, reserves its unique durable stage attempt before transport, and rechecks the grant after waiting. A callback that does not advance the injected clock fails closed. POST is never retried; 404 fallback remains separately bounded by accepted order ID. SD-036 persists retry reservations across handles and restart.

Added `sd153_recovery_review.py`, a pure read-only verifier for a human-signed, short-lived review of the local recovery manifest and planned GET ceiling. It uses a separate signing namespace from the SD-064 network grant and explicitly returns no broker verification, GET/POST permission, database mutation, HALT clear, or release. This proves local dossier/read-plan integrity only; it is not an owner signature or independent reviewer approval.

**Tests:** SD-138 adapter, SD-153 preflight and signed-review suites cover transient retry success, attempt/audit/grant accounting, bad status/delay, no clock progress, revocation during pacing, manifest tamper, expiry, ceiling mismatch, signature forgery, namespace separation, and local error preservation. Full suite **2,070 passed / 2 skipped**; Ruff, mypy (225 files), SQLite Alembic upgrade passed. Code commit `71b7394241a40ce9869246f612a6daae1266bd73` exact-head CI [40699044582](https://github.com/smbabalola/sidedeck/actions/runs/40699044582) passed Python, quality, migration, dashboard and browser jobs.

**Still open:** production transport retry policy/quota approval, remote immutable anchor, authentic broker evidence, named independent reviewer, actual owner authorization and SD-150/151 release. Simulated retry tests do not qualify a real provider or enable transport.

## Findings / independent reviewer requests

| ID | Priority | Review question / open work | Status |
|---|---|---|---|
| R-01 | CRITICAL release gate | Independently verify that owner-bound SD-064 grant, revocation and request caps are always rechecked immediately before every real GET/POST; test broker proxy and delayed 404/429/5xx budgets | OPEN — independent review not started |
| R-02 | CRITICAL release gate | Deploy and independently qualify off-machine immutable SD-145/074 policy, grant-use, audit, baseline and revocation evidence, including rollback/tamper tests | OPEN — requires infrastructure/owner decision |
| R-03 | HIGH | Cross-ledger recovery must use exact OPEN/CLOSE identity, units, baseline and verified broker reads, never merely a locally edited SQLite state; investigate simultaneous restarts and split fills | OFFLINE TESTED IN PART / REVIEW OPEN |
| R-04 | HIGH | Durable offline GET stages plus bounded fake-only 429/5xx retry-after, per-attempt grant/audit/reservation, three-attempt cap and 120-second deadline; real transport quota/pacing and independent review remain required | OFFLINE IMPLEMENTED / independent review and live pacing OPEN |
| R-05 | HIGH | Deterministic local manifest plus separate-namespace signed review verifier; it can validate only local dossier/read-plan integrity and grants no I/O, reset or release authority. Remote authority and authentic broker evidence remain required | OFFLINE VERIFIER IMPLEMENTED / owner workflow and independent review OPEN |
| R-06 | HIGH | Verify protective exit authority after policy expiry, without automatic extension or accepting a forged/revoked grant | OFFLINE TESTED IN PART / REVIEW OPEN |
| R-07 | HIGH | Independent audit of kill-switch release, human role separation, real-vs-sim UI and no Real route | OPEN |
| R-08 | MEDIUM | Test cross-process load/restart and CI soak of negative cases and browser states in a complete operational bundle | OPEN — Bundle O |

**Acceptance for independent review closure:** named independent reviewer, reviewed commit SHA and exact signed finding decisions; remediation plus regression CI; remote ownership/provenance where required. A Codex-generated finding register, GitHub CI PASS, or a local test anchor **cannot** stand in for independent approval.

## Next Batch R work — grouped

**Milestone 3 offline complete:** bounded fake-only transient retries and a distinct-namespace signed local review verifier passed local and exact-head CI. **Next**: independent transport/security review, remote anchor and real broker evidence remain external; continue Bundle O operations/dashboard/soak and Bundle D only from already-authorized offline evidence. Do not call live-provider retry behavior verified.

**Owner-only matters (do not infer approval):** any authenticated Alpaca/eToro requests, remote anchor provisioning, spend, new owner grants/signatures, HALT reset and SD-150/151 Demo activation.
