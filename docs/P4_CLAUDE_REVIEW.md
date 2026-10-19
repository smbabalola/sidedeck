# P4 independent review and hardening (Claude Code, 2026-10-19)

**Status: `P4_DECISION=NO-GO`.** No Saxo credentials were read, no broker or
Saxo endpoint was contacted, and no order (SIM or otherwise) was submitted.
All broker responses in tests are synthetic. Baseline: `0d3cca9` on
`feat/p3-readonly-batch` (203 passed, 1 skipped); review branch
`feat/p4-claude-review`.

## Confirmed defects and fixes

| # | Area | Defect | Fix | Regression tests |
|---|---|---|---|---|
| 1 | C. Operator authorization | `authorize_execution` called `verifier.attest(...)` itself, so the code requesting an order also produced its own "human" approval. | Removed. `ApprovalVerifier` is now verify-only (`verify(attestation, material, principal)`). `accept_operator_approval` only *checks* a signature created outside SideDeck; any verifier exposing `attest`/`sign`/`approve`/`issue` is refused. The approver must differ from the requesting principal. Approval lifetime ≤ 10 minutes. | `test_self_attesting_verifier_cannot_approve_its_own_request`, `test_requester_cannot_approve_and_signature_is_bound_to_exact_order`, `test_approval_expiry_window_and_stale_evidence_are_enforced` |
| 2 | C. Concrete verifier | No real approval verifier existed. | `infrastructure/saxo_operator_approval.py`: `SshSignatureApprovalVerifier` checks an OpenSSH signature (`ssh-keygen -Y verify`, namespace `sidedeck-saxo-sim-approval`) against an operator-managed `allowed_signers` file. SideDeck holds public keys only. | `tests/test_saxo_operator_approval.py` (real throwaway ed25519 key: exact material, principal, namespace) |
| 3 | D. Lifecycle | The submitter never wrote `broker_lifecycle`, so a real acknowledgement could never let fills post. A malformed 2xx (no `OrderId`) was marked `REJECTED`. | The submitter now records `STAGED → SUBMITTING` durably before the POST, then `ACKNOWLEDGED` / `REJECTED` / `UNKNOWN`. A malformed acknowledgement is `UNKNOWN`. Authorization IDs are single-use across orders. | `test_acknowledged_order_links_lifecycle_and_fill_posts_end_to_end`, `test_malformed_ack_is_uncertain_and_explicit_error_is_rejected`, `test_authorization_cannot_be_reused_for_another_order` |
| 4 | D. Uncertain outcome | No path to resolve `UNKNOWN` without guessing. | `reconcile_uncertain_submission` uses read-only account activity (`read_account_activity`, scope-locked cursor). Found → `ACKNOWLEDGED`. Not found → stays `UNKNOWN` (absence is not proof). Conflicting identity → error. Never re-POSTs. | `test_uncertain_order_is_reconciled_read_only_and_never_resubmitted`, `test_account_activity_cursor_cannot_widen_scope` |
| 5 | B. Quote freshness | Quote/FX age was checked against the bundle's caller-chosen `max_age`, so a 10-minute-old quote passed if `max_age` was large. | Every quote/FX timestamp is checked directly against submission time (2 minutes). The request carries `prepared_at`, and submit refuses evidence older than 5 minutes. | `test_stale_quote_cannot_pass_with_a_permissive_bundle_max_age` |
| 6 | B. Precheck provenance | A hand-built `PrecheckEvidence` or fixture parse passed every check. | `run_sim_precheck` seals evidence with a process-local HMAC key. Only sealed evidence can prepare an order, and any field change breaks the seal. | `test_hand_built_or_fixture_precheck_cannot_authorize`, acceptance gate `HAND_BUILT_PRECHECK_REJECTED` |
| 7 | B. Economic consistency | Nothing checked that the broker's USD→EUR rate, EUR cost and EUR cash matched the independent quote and FX. The old fixture had an inverted rate. | Rate within 2% of 1/EURUSD. Account-currency cost matches cost × rate. EUR cash is consistent with notional plus costs (5%). | `test_economically_inconsistent_precheck_is_rejected` |
| 8 | E/F. Accounting binding | `apply_buy_fill` took `authorized_quantity` and `portfolio_id` from the caller. | Fills post only when a durable `CONSUMED` authorization exists for that order key, and the portfolio, account, broker order ID and quantity are read from it. | `test_fill_requires_consumed_operator_authorization`, `test_fill_cannot_post_to_a_portfolio_other_than_the_authorized_one`, `test_fill_quantity_comes_from_the_durable_authorization_not_the_caller` |
| 9 | E. Timestamps / identity | Naive execution timestamps were read as local time. Fill rows weren't checked for instrument or side. | Timezone required (normalised to UTC). Fill rows must carry the expected `Uic` and `BuySell=Buy`. | `test_history_rejects_naive_time_wrong_instrument_and_sell_side`, `test_naive_execution_timestamp_is_rejected` |
| 10 | Schema | `attestation` was `String(128)`, too short for a real signature on PostgreSQL. `broker_lifecycle` was not under Alembic. | Migration `0008_operator_approval_binding`: `attestation` → Text, adds `quantity` and `requested_by`, creates `broker_lifecycle`. | `tests/test_saxo_migration_0008.py`, plus the PostgreSQL CI round trip |
| 11 | Reporting | `saxo_p4_acceptance --offline` printed fixed `PASS` lines without checking anything. | It now exercises the real guards and reports each gate (`PASS`/`MISSING`/`DISABLED`/`NOT_APPLICABLE`), with optional `--json`. GO requires every gate to pass, including the release gate. | `test_offline_acceptance_reports_no_go_with_code_gates_passing`, `test_acceptance_stays_no_go_while_release_is_disabled_even_with_full_evidence` |
| 12 | Kill switch | Submission could be enabled by constructor flags alone. | Added the module constant `SIM_SUBMISSION_RELEASED = False`. No flag, environment variable or CLI can override it. | `test_submission_is_disabled_by_release_gate_even_when_everything_else_is_on` |

Portfolio separation (F): Saxo modules import no Alpaca code
(`test_saxo_execution_modules_cannot_reach_alpaca_paper_accounts`). A SIM fill
can only post to the strategy ledger named in the operator-signed approval.
The other strategy ledger is unchanged (asserted in the end-to-end test).

**Owner decision still open:** SIM fills currently post to the authorized
*strategy* ledger (`tradingagents` or `ai-trading`). If SIM executions should
use a separate SIM-only ledger instead, that is a design change.

## Operator approval procedure (for the future, separately approved step)

1. The operator keeps a private key outside SideDeck. SideDeck is given only
   an `allowed_signers` file, for example:
   `operator namespaces="sidedeck-saxo-sim-approval" ssh-ed25519 AAAA…`
2. SideDeck prepares the request (authenticated account, quote, FX and sealed
   precheck) and prints `approval_material(...)`.
3. The operator reviews the exact payload and signs it:
   `ssh-keygen -Y sign -f ~/.ssh/<key> -n sidedeck-saxo-sim-approval material.txt`
4. SideDeck calls `accept_operator_approval(...)` with the `.sig` contents
   within 10 minutes, and must submit within 5 minutes of preparation.

## What remains before any SIM order

- **Authenticated evidence (Stage 2, separate permission):** a verified SIM
  account and instrument, a current SOFI quote, EUR/USD FX from a trusted
  provider with a `MarketEvidenceVerifier`, and a sealed SIM precheck. All
  read-only. No order.
- **Operator approval:** an operator-held key, an `allowed_signers` file, and a
  signed approval for one exact, freshly prepared order.
- **Release:** a separately approved change of `SIM_SUBMISSION_RELEASED`, plus
  explicit construction of an enabled submitter and transport.
- **Post-submission:** fill reconciliation can only be shown after an approved
  SIM order exists.
