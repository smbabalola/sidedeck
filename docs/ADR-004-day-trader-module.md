# ADR-004: Day Trader as an isolated SideDeck module

## Status

Accepted for offline research and simulation only. Broker execution remains disabled.

## Decision

SideDeck integrates the pinned MIT-licensed `day-trader-skill` as the independently attributable
`DAY_TRADER_SKILL` module. The module runs only through a credential-free, network-blocked sandbox,
normalises untrusted output into SideDeck proposal contracts, and uses the existing decision,
risk, accounting and broker boundaries. It never forwards the upstream broker connector payload.

The initial mode is `RESEARCH_ONLY`; `SIMULATION_ONLY` is permitted only with labelled fixtures or
approved provenance-tagged data. The dedicated virtual book is attribution, not broker-account
creation and not an execution authorization.

## Consequences

- The upstream version, commit, license and per-script digests are pinned in `manifest.py`.
- Eleven capabilities remain visible even when data-dependent stages are unavailable.
- Time Machine results are scenario estimates, not forecasts or strategy-admission evidence.
- Day Trader signals cannot qualify themselves for execution; SideDeck admission and risk remain
  authoritative.
- The workstation exposes a read-only Day Trader surface with no order, capital or permission
  controls.
- A future execution release would require approved intraday data, independent strategy admission,
  a reviewed gateway integration and a separate owner authorization.

## Rejected alternatives

- Replacing the existing pipeline with the skill would create a second uncontrolled control plane.
- Rewriting all eleven skills would lose upstream parity and attribution.
- Calling the skill online from a research worker would expose an unbounded data, credential and
  provider boundary.
