# SD-041 — Dormant eToro Demo write-transport design review (2026-10-21)

**Status:** design only. **No HTTP transport for Demo writes exists in `src/`.** `tests/test_sd041_no_demo_write_transport.py` enforces this: no module may combine a network import with eToro execution or close paths. The existing read client stays a single-path `/pnl` GET.

Execution release remains `NO_GO`, and eToro Real remains `PERMANENTLY_EXCLUDED`.

This document exists so that a future, separately authorized release review (SD-011) can examine a concrete spec rather than an improvised one. It authorizes nothing.

## 1. Interface the transport would implement

The interface is `EtoroDemoTransport.send(method, path, *, reference_id, body, query)` from `sd036_etoro_demo_desk.py`. A real implementation would:

1. Call `require_demo_route(method, path)` again inside the transport, as defence in depth. It must also reject any host other than `https://public-api.etoro.com`.
2. Send `x-request-id = reference_id` for writes. Reuse is only ever the *same* reference with a *byte-identical* body (a hash is stored in lineage). Any other reuse is refused. Reads use a fresh UUID.
3. Use the key pair from the process environment, held privately as in `EtoroDemoReadClient`. It must never accept a bearer token and keys together. It must require a **Demo-environment Write key** that is distinct from the read key, and the owner must confirm that in the portal UI.
4. Disable redirects; use a 15 s timeout and a 1 MB response cap; set an honest `SideDeck` User-Agent; and never retry automatically. Timeouts and resets raise `TransportOutcomeUnknown`. 404 raises `TransportNotFound`. 401, 403, 429 and 5xx raise sanitized errors that carry only a classification, the request ID and the CF-Ray ID.
5. Honour `RateLimit-*`/`Retry-After` by **refusing**, never sleeping. Desk-level `DemoRateBudget` stays authoritative.
6. Log no bodies, IDs, balances or headers. Evidence records only classification, HTTP status and the hash of the request body.

## 2. Threat model (abbreviated)

| Threat | Control |
|---|---|
| Real-money order through a misrouted path | Two allowlist checks (desk and transport), host pin, no Real key accepted, Real permanently excluded |
| Duplicate order after timeout | Write-ahead lineage, recovery by `referenceId` lookup only, never resubmit, kill-switch trip |
| Closing a baseline or manual position | Baseline set refused in both lineage and desk; close requires lineage plus a matching fresh snapshot |
| Forged or confused broker response | Strict parsers: `referenceId` echo, `openingData.orderId` equality, instrument, leverage, side, limit and unit checks |
| Credential leakage | Private attributes, no repr, no logging, no CI usage, no `.env` reads by the transport |
| Runaway automation | Per-intent signed approvals, notional cap, instrument allowlist, open-position cap, documented quotas, kill-switch requiring separate-operator clearance |
| Schema drift (R6) | Strict parsers fail closed; the live checklist (§3) must pass before release |

## 3. Live-schema verification checklist (future, owner-authorized only)

Each step needs its own bounded authorization. None is approved.

1. SD-038: one `/pnl` GET confirms the baseline and the field types.
2. An owner portal UI check: the write key is Demo-environment and Write-scoped; the read key is Demo and Read-only; IP whitelist and expiry are set.
3. A future single-order Demo canary: one approved open of the smallest unit size on one allowlisted instrument, one lookup, one close, one close-info read and one `/pnl` read. That is five requests with a hard cap and no retry. Every response must pass the SD-036 parsers unmodified, or the release fails.
4. Supervised soak (SD-013).
