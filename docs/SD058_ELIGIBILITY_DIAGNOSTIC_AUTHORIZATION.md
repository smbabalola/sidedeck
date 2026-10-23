# SD-058 — MSFT eligibility diagnostic authorization proposal

**Status: PROPOSAL ONLY — not authorized, not signed, not executed.**

This proposal investigates the 2026-10-23 `ABORTED_PREFLIGHT` result without reusing the
completed SD-058 pilot release. It does not authorize a trade, a fresh pilot, a market-data
request, an account read beyond the explicitly named endpoint, or any eToro Real request.

## Requested bounded scope

| Field | Proposed value |
|---|---|
| Broker / environment | eToro Demo only |
| Instrument | MSFT, broker instrument ID `1004` |
| Endpoint | `POST /api/v2/trading/info/demo/eligibility` |
| Body | `{"instrumentIds":[1004],"currency":"USD"}` |
| Maximum requests | 1 eligibility request |
| Automatic retries | 0 |
| Order writes | 0; all order, close, lookup and rates routes refused |
| Expiry | One short owner-selected window, no longer than 30 minutes |
| Credentials | Existing owner-operated eToro Demo read/write pair, used only by the allowlisted diagnostic process; never logged or copied |
| Accounting | Fixed durable diagnostic ledger under the operator data root; no caller-selected budget path |
| Evidence | `PreflightAudit` append-only SQLite record before the diagnostic returns |

The diagnostic must be run only by the owner through a separately signed authorization. The
SD-053/SD-058 pilot signature, digest, budget, window and lock-lift are not valid for this
request. `UNLOCKED_PILOT_DIGEST` remains `None`.

## Evidence retained

The process may retain only privacy-safe evidence:

- UTC timestamp and diagnostic authorization digest;
- request type and durable request count;
- HTTP outcome classification and sanitized parser error;
- response field paths and JSON types;
- non-sensitive currency codes such as `USD`, `GBP` or `EUR`;
- numeric currency identifiers as types only, not arbitrary values.

It must not retain authorization headers, API keys, user/account identifiers, balances, personal
data, raw response bodies, or arbitrary response values. The audit record is append-only and
must be committed before returning either success or `ABORTED_PREFLIGHT`.

## Fail-closed outcomes

- Missing, malformed, non-200, unexpected-schema, non-USD, conflicting or unsupported responses
  produce `DIAGNOSTIC_ABORTED` and no subsequent request.
- A response that reports a non-USD currency is evidence of that response only; it does not
  authorize changing SideDeck's USD requirement.
- A timeout, connection error or uncertain read outcome is recorded as unresolved diagnostic
  evidence and is not retried automatically.
- Any attempt to reach an order, close, lookup, rates, account or Real route is refused before
  network I/O.

## Owner release gates

Before execution, the owner must separately approve and sign the exact proposal digest, confirm
the Demo credential pair and the one-request window, and run the reviewed diagnostic command.
Codex must not sign, unlock, or execute it. After the response is captured, engineering stops at
the evidence boundary until the result is independently reviewed. A new supervised buy-and-close
pilot requires a newly prepared and separately signed intent, fresh window, fresh request budget,
and a verified root-cause correction; this proposal cannot be upgraded into that pilot.

