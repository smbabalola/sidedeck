# Bundle D — existing-data SWING admission packet

**Decision date:** 28 October 2026
**Overall verdict:** **BLOCKED_EXTERNAL / NO_GO**
**Execution admission:** NONE
**Data/provider calls or subscription:** NONE

## Decision

No SWING strategy is admitted. This checkout contains no SPY, QQQ or MSFT historical bar bundle or signed source manifest that can be independently re-evaluated: the tracked-file inventory contains no research datasets, and the local `data/` tree has no bar files for these instruments. The historical results below are preserved in the committed research reports, but they cannot be regenerated from the current checkout. This packet therefore does not claim a fresh OOS run or verify the original observations independently.

The existing source decision records Alpaca as the owner's preferred candidate and the source as **not approved** for SideDeck use. The public terms describe personal/non-commercial use and restrict reproduction/distribution; they do not establish the precise account entitlement, storage/replay permission, or use of Alpaca data to make decisions for eToro Demo. [Alpaca Terms and Conditions](https://files.alpaca.markets/disclosures/library/TermsAndConditions.pdf), [Alpaca redistribution FAQ](https://alpaca.markets/support/redistribute-alpaca-api), and [Alpaca market-data plans](https://alpaca.markets/data). These public terms are not an account-specific grant or a legal determination. No new authenticated reads, purchase, data acquisition or credential use was performed.

The last documented SPY/QQQ/MSFT observations end **20 October 2026**; they are stale for execution on this decision date, and historical daily bars do not provide a current eToro send-time quote. The existing admission path still requires genuine point-in-time five-minute input and at least **30 locked-OOS trades**; this packet does not relax the rule or substitute daily data.

## Existing documented research findings (not rerun here)

`docs/SD103_INTEGRATED_PIPELINE.md` reports single-instrument 80/20 locked-OOS counts below 30 for the channel mean-reversion candidate (SPY 12; QQQ 12; MSFT 14), with MSFT rejected. `docs/SD106_SD112_EVIDENCE_AND_POOLED_METHOD.md` reports the later pooled analysis through 20 October 2026:

| Candidate | Historical documented verdict | Reported OOS evidence | Current packet status |
|---|---|---|---|
| Channel mean reversion | REJECTED | 76 trades; effective sample 39.1; PF 1.15; bootstrap lower PF 0.56; PF 0.92 at 2× costs; concentration criterion failed | **FAIL — do not admit** |
| Liquidity sweep reversal | INSUFFICIENT_EVIDENCE | 20 trades; effective sample 14.0; bootstrap lower PF 0.31 | **BLOCKED_EXTERNAL / insufficient evidence** |
| Moving-average trend | INSUFFICIENT_EVIDENCE | 23 trades; effective sample 11.0; bootstrap lower PF 0.07; a market regime lacked coverage | **BLOCKED_EXTERNAL / insufficient evidence** |

The channel strategy's documented pooled count crosses the numeric sample floor but fails the uncertainty, doubled-cost and concentration requirements. The other two do not meet the effective-sample requirement. None qualifies for promotion. Historical report figures are quoted as prior documented findings, not represented as re-computed measurements in this batch.

## Provenance and admissibility gates

| Gate | Evidence in current checkout | Result |
|---|---|---|
| Raw SPY/QQQ/MSFT bars and per-file hashes | No tracked bar bundles or current signed manifests found | **BLOCKED_EXTERNAL** |
| Alpaca account-specific SIP entitlement for these observations | Historical reports describe prior retrieval; current entitlement not verified | **BLOCKED_EXTERNAL** |
| Rights for SideDeck retention/replay and eToro cross-broker research use | Public standard terms do not settle this specific use | **BLOCKED_EXTERNAL** |
| Point-in-time membership, corporate actions and adjustment basis | Prior methodology reports split-adjusted data and survivorship limitations; no source bundle available here for validation | **BLOCKED_EXTERNAL** |
| Fresh eToro execution bid/ask and instrument mapping | No current separately authorized broker evidence | **BLOCKED_EXTERNAL** |
| Independent strategy reproduction and signoff | Not supplied | **BLOCKED_EXTERNAL** |
| Strategy admission (`>=30` locked-OOS trades and all robustness/cost/risk rules) | Existing documented candidates fail or are insufficient | **NO_GO** |

## Reproduction path when admissible evidence is available

1. Resolve the data contract/entitlement and account-specific rights outside this packet. Use only an owner-approved bounded acquisition scope; this report grants none.
2. Restore the original signed data manifests and raw bundles through the approved local evidence process; record hashes and verify source, instrument mapping, dates, adjustments, session coverage and point-in-time membership before research.
3. Re-run the documented `sd103_trading_pipeline` decision/replay and `sd112_pooled_admission` methodology using the unchanged locked split, costs, minimum-sample, bootstrap and concentration criteria. Preserve prior looks and the sealed future holdout; do not re-arm or unseal it from a code change.
4. Obtain independent reproduction and explicit strategy admission before any execution path can consume a signal.

The existing fixture suite proves software plumbing only. Synthetic fixtures, saved summary reports and a successful simulator replay cannot change this verdict to PASS or make a strategy executable.
