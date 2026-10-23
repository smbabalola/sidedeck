# ADR-001: real-model smoke boundary

## Decision

SideDeck permits only an explicit, one-request local model smoke test. The
default remains offline. Ollama is preferred, followed by an explicitly chosen
NVIDIA request and finally a small OpenAI fallback. The command requires
`--allow-network-model-test`, sends synthetic non-sensitive context, caps output
tokens, makes no automatic retries, and writes only redacted metadata to the
ignored `results/` directory.

The pinned TradingAgents runtime, provider inference, proposal normalization,
SideDeck schema validation and risk evaluation are separate evidence fields.
An upstream rating string or incomplete trade cannot become an executable
SideDeck proposal. No model output can call a broker or mutate a ledger.

## Consequences

The repository remains network-free in CI and does not depend on provider SDKs.
The local smoke CLI uses the standard library HTTP client. Actual upstream
TradingAgents execution requires its pinned runtime in a disposable environment;
if its graph cannot be constrained to the approved synthetic context, the result
must be recorded as provider-only rather than claimed as a valid historical run.
