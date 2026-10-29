# Bundle G — independent readiness register

**State:** `NO_GO` · **Independent reviewer:** NOT APPOINTED / NOT SIGNED
**eToro Demo:** `NOT_RELEASED` · **historical kill switch:** `HALTED` · **eToro Real:** NEVER

This is an engineering-maintained blocker register, not an independent review, owner approval or release dossier signoff. The facts below remain open until the named evidence is supplied by the proper party.

| Gate / finding | Current evidence | State | Closure evidence required |
|---|---|---|---|
| G0 — data rights and acquisition | Alpaca is the preferred candidate, but current account entitlement and rights for SideDeck replay/cross-broker use are unresolved; original SPY/QQQ/MSFT source bundles are unavailable in this checkout | **BLOCKED_EXTERNAL** | Account-specific written entitlement/use scope and owner-approved bounded acquisition; preserved raw files and signed source manifests |
| G1 — strategy admission | Prior pooled research rejects channel mean reversion on robustness/cost/concentration; liquidity sweep and moving-average candidates have insufficient effective samples | **NO_GO** | Reproducible, independent locked-OOS evaluation of genuine admissible data meeting every existing criterion, including the 30-trade floor |
| G2 — Demo lifecycle and recoverability | Fake lifecycle, durable recovery and fault controls have offline tests; Bundle O composed restart/protective-expiry scenario now verifies rehydrated fill facts and final simulated reconciliation; local full Python, static, migration, web unit/build checks passed | **OFFLINE EVIDENCE ONLY; exact-head CI `40706936495` passed on `7dd4932e6f68263b6f860be2653f5c20c1b3373b`** | Green exact-head CI, named independent review of crash/restart and cross-ledger recovery, and later authentic separately authorized broker reconciliation |
| G3 — audit, identity and operator controls | Local append-only/fail-closed interfaces and a newly exposed read-only local worker diagnostic exist; no deployed externally controlled anchor or authenticated operator delivery | **BLOCKED_OWNER / EXTERNAL** | Owner-approved remote anchor deployment, independently tested identity/role separation, immutable provenance and delivery evidence |
| G4 — release scope | No current signed release digest, owner-authorized strategy/data combination, confirmed account mapping or authorized HALT reset | **BLOCKED_OWNER** | Exact owner-signed scope, independent review, correct account and protected-baseline evidence, plus separate HALT decision if ever justified |
| R-04/R-05 — retry/review verification | Offline bounded fake GET retry and distinct-namespace signed local review verifier passed CI `40699480581` at `c4c0fb9` | **VERIFIED_OFFLINE; NOT INDEPENDENTLY REVIEWED** | Named independent security reviewer and decision on the exact reviewed SHA |
| O-148 — integrated operational soak | Cross-session partial-fill/restart/protective-expiry/final-reconciliation path; revoked-grant incident and altered-fill restart regressions added. DAY flatten/DST/early-close aggregate soak remains | **IN_PROGRESS** | Full test/security suite and exact-head CI `40706502546` passed on `0196981a5536ac3807c970f52cf1449332640ad7`; publish reproducible scenario summary and obtain independent review |

**Bundle D strategy packet:** [SD153_BUNDLE_D_SWING_ADMISSION_PACKET.md](SD153_BUNDLE_D_SWING_ADMISSION_PACKET.md), verdict `BLOCKED_EXTERNAL / NO_GO`. Prior documented channel strategy fails robustness/cost/concentration; other candidates lack effective sample. No source bars/manifests are in this checkout, account rights remain unresolved, and historical data are stale for execution.

No row in this table grants a broker request, risk-policy modification, HALT reset, data purchase, deployment or Demo release. The only permissible aggregate result today is **NO_GO**.
