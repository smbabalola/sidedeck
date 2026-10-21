# SD-025 benchmark/report integration

Strategy validation summaries now accept optional offline SD-023 audit files
and expose a sanitized `benchmark` object per dataset. The object contains the
price-only convention, ending equity/return/drawdown, corporate-action status,
and an explicit total-return availability field. Unloaded or malformed audits
fall back to `UNAVAILABLE` / `NOT_ASSESSED`.

The loopback API remains read-only, proposal-only and broker-disabled. It does
not expose raw bars, source URLs, credentials, account identifiers or order
controls. `UNAVAILABLE` total-return data cannot be rendered as an investor
return by the API contract.

Use `--strategy-audit PATH` alongside `--strategy-research PATH` when starting
the local dashboard API. The audit input is local JSON only; no transport was
added.
