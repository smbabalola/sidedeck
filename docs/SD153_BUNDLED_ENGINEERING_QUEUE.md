# SideDeck — Bundled autonomous engineering queue

**Created:** 28 October 2026 · **Branch:** `codex/sd122-etoro-data-autodemo-20261027` · **PR:** [#8](https://github.com/smbabalola/sidedeck/pull/8)

**Authority and precedence:** `AGENTS.md` → `SIDEDECK_STEERING.md` §§20–21 → `STEERING.md` → authoritative live `TODO.md`. This document is a **work-package scheduler, not a change to safety policy or a broker release**. The Codex session can continue working without routine “proceed” messages while active; this markdown does not start or sustain background execution.

## What bundling means

Execute a coherent cross-file engineering package, not an individual TODO tick. Within the **same active development session**, select the highest-priority unblocked package, implement several related SD tasks together, test negative and normal paths, run full checks, push reviewed commits, check exact-head CI, update TODO and move to the next unblocked package. Work is complete only if its package acceptance evidence is linked; a green test suite never substitutes for an independent security signoff or genuine market evidence.

**Concurrency:** have a *single writing owner per branch/worktree*. Other lanes can be researched or verified independently, but Codex must not allow multiple agents to overwrite the same TODO/STEERING, security or execution files. Use separate isolated branches/worktrees and PRs for truly concurrent writers; rebase/retest in a reviewed order. The current main integration branch stays the existing draft PR #8; no merge without explicit approval.

## Bundle R — Finish broker safety and restart reconciliation

**Priority: first integration bundle.** Tasks: **SD-138 + SD-139 + SD-141**, with **SD-145** independent-anchor interface checks and the SD-152 recovery dossier.

**Already delivered offline:** durable fake OPEN → owned position → reduce-only CLOSE → strict fake `/pnl`; full protected original baseline, accepted→404 signed GET fallback, grant revocation, partial/split-fill, hard OS-child crash, cross-ledger discrepancy, orphan positions and book/instrument/quantity tamper tests. Latest verified implementation `419e324`, [CI 40664791594 PASS](https://github.com/smbabalola/sidedeck/actions/runs/40664791594): 1,932 passed / 2 skipped. Avoid reimplementing these.

**Remaining bundled implementation:**
1. Production-shaped **fake** GET retry pacing, deadline, quota and per-intent grant budget. Every network-shaped read requires the existing separately signed/granted reference, pre-send anchored audit and fresh expiry check. Unknown order or unavailable evidence **HALTS**; 404 must not trigger POST replay.
2. Cross-ledger crash/poison/corruption matrix around `SD-036`, `SD-063`, `SD-129` and `SD-152`: restart/cold-start, multiple handles, stale leader, partial/multi-fill and duplicate intent; explicitly distinguish `GET_ONLY_RECOVERY_POSSIBLE` from `REQUIRES_INDEPENDENT_WHOLE_ACCOUNT_REVIEW`.
3. Define an **operator-only signed recovery protocol and dry-run verifier** (no reset action, no self-grant, no durable DB edit): bind preserved original baseline, broker evidence, external anchor, policy/lineage identities, expiry and per-call ceiling; output `RECONCILED` or `UNRESOLVED` with missing-evidence reasons. Nothing from this package may clear a historical HALT or enable broker sockets.
4. Record an independent-review request and security finding register. Independent reviewer approval and real external immutable anchor **remain open**, never self-attested by the coding agent.

**Acceptance:** executable offline recovery, retry-limit and fault-matrix tests; zero unintended GET/POST; no release branch or actual account access; full exact-head CI; independent findings remain visibly unresolved until genuinely signed off.

## Bundle O — Complete offline autonomous operation, protection and dashboard

**Priority: next once Bundle R's key contracts are stable; UI can be built in parallel.** Tasks: **SD-140 + SD-152 + SD-147 + SD-148**, using existing SD-125/126 DAY controller and SD-068 scheduler. Do not create a shadow trading engine.

**Remaining bundled implementation:**
1. Integrate **DAY/SWING/POSITION** scheduling with separate track rules, US market DST and early closes. Enforce DAY last-30-minute buy blackout and 10-minute pre-close flatten; overdue/unknown close means overnight incident/HALT. SWING retains exit-first, horizon/stop rules.
2. Enforce protective grants for long-held positions with a **read-only upcoming expiry/renewal request** and independent human signing/revocation. A protected close requires fresh quotes and new valid authority; expiry may not auto-renew or extend grant lifetime.
3. Complete offline single-writer service lifecycle, durable worker health, operator alerts via an **in-process/offline fixture sink** (not email/SMS or external account), incident deduplication, persistent operator-visible status. False claims of being flat, unverified quotes and auto-reset are prohibited.
4. Build/read-test **SD-147 non-executable dashboard** (desktop/tablet/mobile): simulation vs actual broker explicitly labelled, data/strategy gate, lock status, baseline fidelity, unknown entries/closes, audit and owner-only blockers.
5. Add **SD-148 deterministic multi-session soak** for no signal, stop, policy expiry, DST/half-day, restart, orphan order, delayed 404, partial fill and anchor outage. Report incident counts and failed invariants, not fabricated profitability.

**Acceptance:** complete offline scenario matrix including browser E2E, never double-send, kill on unresolved outcomes, all holdings protected; full exact-head CI and operational runbook. Remote alarm delivery, owner-signed deployment, independent service security review remain separate external gates.

## Bundle D — Establish an admissible swing strategy with existing lawful data

**Parallel research lane; no provider calls without new bounded authority.** Tasks: **SD-143 + SD-144**; reuse SD-142 evidence pipeline, SD-014–022 backtest/walk-forward and SD-071 minimum-trade gate.

**Remaining bundled implementation:**
1. Audit **existing** lawful Alpaca SIP SPY/QQQ/MSFT daily evidence, precise permitted usage, symbol/instrument/timepoint provenance, adjustments, data ageing and whether eToro Demo cross-broker research use is allowed. Use no fresh authenticated reads or paid subscriptions.
2. Propose a **formally reviewed SWING-only cadence decision**. Five-minute DAY requirements continue unchanged. A daily SWING admission path may be introduced only if the independent admission contract and its negative tests are explicitly amended and reviewed; not by changing a flag or relabelling data.
3. Run deterministic train/walk-forward/locked OOS robustness, costs, spread and risk sensitivity on admissible historical evidence. Current `>=30` OOS-trade minimum remains in force unless independently changed; reject insufficient-data and synthetic outcomes.
4. Deliver one strategy-evidence packet with locked identity/hash and **`PASS`, `FAIL` or `BLOCKED_EXTERNAL`** plus reproducibility commands and evidence gaps. Do not invent an edge or imply a research survivor is execution-admitted.

**Acceptance:** source-backed data-rights matrix, source-provenance checks and independent reproducible OOS verdict. If licensing, freshness, sample count or final execution-price validation is absent, the correct deliverable is an explicit **BLOCKED_EXTERNAL / NO_GO** decision packet, not an artificial PASS.

## Bundle G — Independent readiness and consolidated owner decision

**Start a review register in parallel; final gate after R/O/D evidence.** Tasks: **SD-146 + SD-149**, with findings from SD-138/139/140/141/145/148/152.

**Deliverables:** independent security/operations review and remediation; production-shaped but **LOCKED** release-dossier matrix (G0–G4), source/data/admission proof, owner-authenticated external immutable baseline/audit proposal, instrument/book allocation, scoped per-route GET/POST limits, stop and fault protocol, one unsigned/expiring proposed virtual-money canary. Consolidate true owner decisions for external feed entitlement, off-machine audit deployment and Demo execution *only at the relevant hinge*.

**Acceptance:** independent signoff with named remaining blockers; verifiable CI, QA and read-only report; explicit `NO_GO` for missing gates. Codex never signs as the human owner.

## Release fence — explicitly NOT part of any engineering bundle

**SD-150** human owner-only approval/signature and separate kill-switch-reset authority. **SD-151** limited released eToro Demo pilot and one-month monitored trial, only after signed gates and real broker evidence. Neither is approved or scheduled by this document. `ETORO_DEMO=NOT_RELEASED`, `broker_execution=DISABLED`, historical kill switch `HALTED`, four original Demo positions **PROTECTED**, **eToro Real NEVER**. Never reuse prior signed diagnostic permissions; no paid data, real eToro/Alpaca requests or external alert provisioning without new scoped permission.

## Continuous batch operating protocol

1. **Reconcile:** fetch latest worktree HEAD, active PR, CI and authoritative TODO; do not trust historical status lines. Treat a concurrent pushed change as a rebase/review point.
2. **Choose:** complete **R** first, then dependency-ready **O**; advance **D** independently and queue **G** review findings. Do not wait for every outside dependency: work on another safe offline batch instead.
3. **Execute grouped slice:** create tests and code spanning multiple related SD IDs; commit discrete reviewed changes and preserve isolation. Cap each slice at the next coherent fully testable unit; do not defer testing until the entire bundle is done.
4. **Verify:** run focused and full Python tests, Ruff, mypy, disposable SQLite/Postgres where possible, dashboard build/unit and browser E2E. Run exact-head GitHub CI; record passing SHA, test counts, skips and any red→green defect.
5. **Report once per bundle milestone:** update TODO's bundle status and SD rows with checked acceptance, residual external blockers and a concise PR review comment; do not repeatedly hand off tiny trivial tasks or claim closure because a feature works on fixtures.
6. **Proceed:** choose the next unblocked coding slice while the session remains active, without routine owner "proceed" messages. **Stop only** at owner-controlled external reads/writes/spend, release/kill reset, independent signoff, or a real security/data blocker. This file does **not** initiate background activity.

**Owner-facing handoff format:** bundle → changed SD IDs → tested evidence (SHA/CI/pytest) → blocked external decisions → next offline bundle. Do not confuse “offline tested” with “released”, “profitable”, or “fully complete.”
