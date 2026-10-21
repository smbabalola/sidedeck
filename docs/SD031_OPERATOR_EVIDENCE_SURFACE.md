# SD-031 operator evidence surface

SD-031 adds a read-only `/api/research/release-gate` route and a dashboard
panel for the sanitized SD-030 paper-release report. The API accepts only a
small allowlist, rejects symlinks, oversized or malformed files, and defaults
to `NO_GO` with paper-order submission `DISABLED` when the report is absent or
tries to enable release.

The browser uses the same fail-closed defaults and displays the remaining
owner-controlled gates: separate approval, account mapping, reconciliation and
kill-switch release. It does not add controls for broker orders or account
access. No network, credential, paper-order or live-trading operation is used.
