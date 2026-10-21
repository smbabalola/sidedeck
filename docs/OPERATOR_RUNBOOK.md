# SideDeck operator runbook

Status: offline/local only. No broker or provider access is enabled by this
runbook.

## Start and verify

1. Confirm the checkout is `feat/p5-agent-adapters` and inspect `git status`.
   Preserve `.env`, local databases, `SideDeck-Blueprint/` and other untracked
   work; do not reset or clean them.
2. Run the verification commands in the repository README.
3. Run the deterministic demo with `PYTHONPATH=src` and inspect only labelled
   fixture/simulation outputs. Never interpret them as live prices or fills.
4. For the dashboard, start the Python loopback API on `127.0.0.1:8765`, then
   run the Vite app on its loopback host. If the API is unavailable, the UI
   must show an unavailable state rather than inventing positions or cash.

## Recovery and rollback

- Stop the local process and preserve its stdout/stderr for sanitized review.
- Do not retry an authenticated provider or broker request after a timeout or
  ambiguous response. Record the endpoint class, UTC time and safe error type
  only; obtain fresh authorization before any new request.
- For a local SQLite artifact, copy it to a new operator-approved backup path
  before inspection. Restore only into a new disposable path, run migrations
  and replay checks, and compare counts/hashes without opening a user database.
- If a migration fails, stop. Do not downgrade an existing user database;
  reproduce the round trip against a disposable SQLite file or CI PostgreSQL.
- Any eToro Demo baseline discrepancy is a stop condition. Existing baseline
  positions are immutable, unattributed and never closed or reclassified by
  SideDeck.

## Privacy and release stops

Never print or commit credentials, account IDs, raw broker payloads, private
datasets or raw model output. Do not load `.env` for an offline run. Paid model
calls, authenticated GETs, paper/demo orders and capital allocation each need
their own bounded owner authorization; this runbook does not grant it. Real
money execution is permanently out of scope.
