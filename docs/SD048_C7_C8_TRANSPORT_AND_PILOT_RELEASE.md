# SD-048 — C7 eToro Demo transport and C8 signed pilot release (2026-10-22)

**Status:** implemented and offline-tested; **locked**. The owner authorized building and offline-testing only. There were no authenticated requests or orders, no capital was allocated, and there was no pilot release.

`ETORO_DEMO_EXECUTION_RELEASE=NO_GO`, `broker_execution=DISABLED`, `NETWORK_TRANSPORT_ENABLED=False`. eToro Real is permanently prohibited.

## C7 — `infrastructure/etoro_demo_write_transport.py`

- Implements the SD-041 spec:
  - only documented Demo routes, via `require_demo_route`; Real and Agent Portfolio routes are refused before any I/O;
  - the host is pinned;
  - no redirects and no retries;
  - 15 s timeout and 1 MB response cap;
  - an honest User-Agent;
  - credentials are held privately and hidden from `repr` and errors.
- Writes send `x-request-id = referenceId`, and a reference can only be re-sent with a byte-identical body. Reads use a fresh id. The lookup query accepts exactly one of `referenceId`/`orderId`.
- On a **write**, any of these raises `TransportOutcomeUnknown`, and the desk then trips the kill-switch and recovers only by lookup, never by resubmitting:
  - a timeout or reset;
  - a 5xx;
  - a non-200;
  - an oversized or malformed body;
  - a redirect.
- 404 raises `TransportNotFound`. 400/401/403/429 raise sanitized errors.
- **Lock:** construction requires an active C8 `PilotRelease`, **and**, while `NETWORK_TRANSPORT_ENABLED=False`, an injected opener. Without one, the constructor refuses. Nothing in `src/` constructs the transport (an AST guard enforces this). Only `etoro_demo_client.py` (GET `/pnl`) and this module may carry eToro authentication headers.

## C8 — `application/sd048_pilot_release.py`

- `PilotIntent` holds the broker, pilot id, strategy, instrument, units, limit, reference price, notional cap, request caps and the `not_before`/`expires_at` window. It has a canonical JSON form and a SHA-256 digest. The owner signs that digest with their SSH key (SD-045; dedicated namespace `sidedeck-etoro-pilot-release`).
- `authorize_pilot` issues a `PilotRelease` only if **all** of these pass:
  1. **Intent bounds:** Demo only; caps ≤ SD-044 (11 requests / 2 writes); ≤ USD 50; units × limit ≤ the cap; limit ≤ +0.5 %; window ≤ 8 h, containing now; UUID pilot id.
  2. **Scope:** a strategy book, and an instrument not in the protected baseline.
  3. **Independent gates:** the single-pair credential policy, baseline `MATCHED`, kill-switch clear, pilot budget unused, signers configured.
  4. **Signature:** valid for the configured principal over the exact digest.
  5. **Single use:** the pilot id and digest are consumed, so replays are refused.
- A `PilotRelease` cannot be forged (private construction token) or mutated, and it is re-checked on every send and every open.
- The desk accepts a non-simulated transport only with an active release whose intent matches its policy (that one instrument, notional ≤ the cap, 1 open position). Every open must equal the signed intent. The close still needs its own SD-033 approval.

## Tests (offline; mock openers route `urllib` requests into the simulator; throwaway SSH keys)

`tests/test_sd048_c7_c8.py` (48 tests) covers:
- a valid release and replay refusal;
- tampering with each signed field;
- a wrong key or principal;
- each independent gate failing on its own, which proves a signature alone is insufficient;
- intent bounds;
- forging and mutation;
- the network lock;
- Real and Agent Portfolio refusal before I/O;
- headers, ids and credential hiding;
- reference reuse;
- failure classification (timeouts, 5xx, malformed, oversized, 401/403/429/404), with no retries;
- an expired release blocking a send;
- desk refusal without a release or with a mismatched policy;
- a full pilot to `COMPLETE` through the real transport code;
- an open differing from the intent;
- an interrupted open recovered with no resubmission;
- an unresolved close;
- a malformed open response;
- a second open never reaching the broker.

`tests/test_sd041_no_demo_write_transport.py` adds the lock and no-construction guards.

## Independent security review (2026-10-22) and remediation

A separate read-only security-review agent examined C7, C8, the desk, the pilot runner, the verifier and the guards. **No critical findings.** It confirmed:
- no default network path in this phase;
- Real and Agent Portfolio routes are refused;
- redirects are refused and there are no retries;
- idempotency, Decimal and timezone canonicalisation, release immutability and baseline protection hold;
- the UNRESOLVED rule holds;
- no credentials leak.

All HIGH and MEDIUM findings were fixed, each with a regression test:

| # | Finding | Fix |
|---|---|---|
| H1 | Signed caps and scope were enforced only at release time or in a caller-chosen budget | The transport keeps a persistent per-release ledger keyed by the digest and capped by the **signed** caps. Every order body must equal the signed intent; closes must be full closes of the signed instrument |
| H2 | Gates, verifier and store were caller-asserted | `authorize_pilot` requires `SshSignatureVerifier` with the dedicated `sidedeck-etoro-pilot-release` namespace. In-memory ledgers are refused. `ReleaseGates.from_runtime` computes the gates from live objects |
| M3 | Some write failures escaped classification | Any failure once write I/O starts, including 408/5xx, protocol errors and unreadable bodies, gives `TransportOutcomeUnknown`. The desk now treats *any* write-send failure as an unknown outcome and halts |
| M4 | An unreadable 200 acceptance did not halt the desk | The desk sets `OUTCOME_UNKNOWN` and trips the kill-switch |
| M5 | A second close was allowed while one was pending | Refused while any close on that position is unsettled |
| M6 | A 404 after an unknown open was recorded as a rejection | Now `NOT_FOUND_INCONCLUSIVE`: the desk stays halted, no rejection is recorded, nothing is resubmitted |
| M7 | Windows could resolve `ssh-keygen` from the current directory | A binary resolved from the current directory is refused |
| M8 | A shared signing namespace; loose intent typing | A dedicated pilot namespace; strict `strategy`/`instrument_id` types; canonical lowercase UUID pilot id |

LOW items addressed:
- exact-match (`fullmatch`) route, principal and digest regexes;
- real `urllib` openers can't be injected;
- `offline_simulation` is a read-only `False`;
- responses are closed;
- credential header values are validated.

Accepted residual: Python cannot hide in-process objects (for example, a caller could import private names). The threat model is accidental misuse and outside input, not hostile code running inside SideDeck. That is why the network lock is a reviewed source constant and the desk, transport and release each re-check independently.

## Still required before any pilot (SD-047)

- C3 (owner signing key and test signature);
- C9–C11 (≤ USD 50 allocation, instrument and its eToro ID, date window);
- a separate reviewed commit to lift the network lock;
- the owner's explicit, signed pilot authorization.
