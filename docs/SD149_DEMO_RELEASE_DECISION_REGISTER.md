# SD-149 — eToro Demo canary decision register (NOT RELEASED)
2026-10-29 | Repo: smbabalola/sidedeck | Draft PR #8 | Simulation-only review

## Evidence provenance and statuses
This is a **reviewer handoff**, not an independent security attestation or a trade authorization. Green test results qualify only their tested scope.

| Gate | Verdict | Evidence | Independent prerequisite |
| --- | --- | --- | --- |
| Offline lifecycle CI | PASS (simulation only) | code `07006e3`, CI [40852549194](https://github.com/smbabalola/sidedeck/actions/runs/40852549194): standalone worker can reopen local simulated position and close using distinct signed quotes; crash fence and cross-session soak | None for completed fixture demonstration |
| Release-head CI | PASS for earlier docs head | docs `f86835c` CI [40855038338](https://github.com/smbabalola/sidedeck/actions/runs/40855038338) | Exact release SHA and independent review before canary |
| G1 data rights and freshness | BLOCKED_EXTERNAL | SD-021 daily SIP research, SD-142/143 pipeline described in `docs/AUTONOMOUS_DEMO_EXECUTION_PLAN.md` | Provider agreement and source identity, automation/cross-broker/storage rights, timely executable price evidence |
| G2 verified market input | NOT_ASSESSED externally | SD-074 nonce/signature contracts verified in fixture tests | Authorized actual provider instrumentation, as-of timestamps, spreads and cutoff review |
| G3 strategy admission | NO_GO | SD-155 native ORB fixture-only signal; prior genuine ORB backtest not qualified | Independent locked out-of-sample >=30 qualified trades with costs/slippage and final holdout; explicit signer independent of strategy |
| G4 security and operations | BLOCKED_EXTERNAL | SD-145 local anchor interface; SD-146/149 security review plans; SD-152 durable single-writer | Independently deployed off-machine append-only anchor, review findings, incident/alert/rollback owner and process supervisor |
| G4 owner scope / historical HALT | BLOCKED_OWNER | §21 `SIDEDECK_STEERING.md`; old pilot HALTED and 4 protected Demo holdings | Fresh baseline and signed, expiring, bounded owner release plus distinct authorised reset after reconciled state |
| G5 canary | NOT_RELEASED | Never executed by this workstream | All prior release gates PASS, independently monitored Demo-only open/fill/close and fresh /pnl baseline reconciliation |

## Specific evidence decisions from committed packets (29 October review)

- **Data, SD-143:** `docs/SD143_INTRADAY_SOURCE_DECISION.md` records the owner's Alpaca preference, but no authorisation for new intraday requests. Historical SIP coverage and public provider terms do **not** establish this account's permitted storage, replay, personal/business use, or cross-broker eToro signal rights. The proposed SPY 5m read remains unsigned and unperformed. TradingView chart data is not accepted as an automated feed.
- **Strategy, Bundle D:** `docs/SD153_BUNDLE_D_SWING_ADMISSION_PACKET.md` explicitly reports no reproducible raw SPY/QQQ/MSFT bars or signed manifests in that checkout. Its reported pooled channel mean reversion was **REJECTED** despite 76 historical OOS trades: PF 1.15, bootstrap lower PF 0.56, PF 0.92 with 2× costs and concentration failure. Liquidity sweep (20 trades) and MA trend (23 trades) were **INSUFFICIENT**. These are previously recorded figures, not a fresh reproduction. **G3 is FAIL/NO_GO for these candidates**, not just pending signatures.
- **Security, Bundle R:** `docs/SD153_BUNDLE_R_SECURITY_REVIEW.md` reports offline-tested durable per-stage recovery GET fences, bounded transient fake GET retries and unsigned evidence manifests. It explicitly lacks remote immutable anchors, independently signed review, authentic broker evidence and independently authorised operator recovery.
- **Operations, Bundle O:** `docs/SD152_BUNDLE_O_SECURITY_OPERATIONS_CLOSURE.md` identifies unauthenticated operator identity, unverified alert delivery and no deployed watch/alert service or external anchor. A local outbox record is not a delivered alert.
- **First external dependency:** a legitimate provider-specific entitlement and data-path decision (e.g. the existing Alpaca candidate) with fresh raw reproducible bars. This alone cannot produce strategy admission; genuine research must still pass. Do not request a Demo order release now.

## Non-negotiable canary acceptance contract
1. Only eToro virtual Demo; eToro Real permanently excluded. The existing historical HALT is not reset from engineering authority.
2. Explicit fixed strategy, immutable digest, symbol and book; hard time, cash, exposure, position, write and request caps. A signer separate from the autonomous strategy/controller approves the digest.
3. Preserve four protected preexisting position identifiers and verify the same IDs, directions, instruments, units and opening times before and after. Unchanged ticker alone is insufficient.
4. Require durable intent/order/position lineage and one broker POST per approved intent. Unknown 404 or ambiguous fill means read-only recovery / HALT, never another opening POST.
5. Separate expiring quote envelopes, external append-only checkpoints before any send; full reduce-only exit of SideDeck-owned positions only; final fresh /pnl shows zero attributable position/pending order without protected baseline modification.
6. One-month monitored Demo soak begins only after independently witnessed single full canary and approved operator recovery. No promise of profitability.

## Next permitted work without owner input
- Independent reviewers may inspect the existing offline fault matrix, deployment and security finding register, and the already retained source-rights documents. Missing proof remains BLOCKED/NOT_ASSESSED.
- No provider reads, quote endpoints, new entitlements, fees, credential handling, audit-host provisioning, owner signatures, HALT resets or brokerage requests.
- Request exactly the missing, scoped authorization when an actionable prerequisite is ready (data entitlement or external audit deployment first). Do not solicit premature trading authority.

**Decision: G5 NO-GO / NOT_RELEASED.** SD-DAY-FINAL mechanical acceptance remains PASS in its controlled offline scope. This release register may be revised only with directly linked evidence and independent gate ownership.
