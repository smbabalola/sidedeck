# M2 dual-agent runtime verification

Status: offline verified / real research blocked. Broker execution remains
disabled and `P4_DECISION=NO-GO`.

## Isolated runtime findings — 2026-10-20

| Runtime | Finding |
|---|---|
| TradingAgents | Package import succeeded in `../TradingAgents/.venv`; installed package version `0.7.0`; `TradingAgentsGraph` and `propagate(company_name, trade_date, asset_type='stock', portfolio=None)` verified. |
| AI Hedge Fund | `hedge_fund` package and Buffett v2 contract modules imported in `../ai-hedge-fund/.venv`; `BuffettAgent.predict(ticker, date, data_client)` and snapshot API signatures verified. |
| TradingAgents preflight | `READY_TO_ATTEMPT` under the configured provider; this was a local presence check only. No provider call was made. |
| AI Hedge Fund preflight | `BLOCKED`: required model and Financial Datasets credentials were absent. No provider call was made. |

The preflight output exposed only boolean credential status. No key, token,
raw provider response, account data or broker credential was printed or
stored. The upstream contract probe did not instantiate an agent, call an LLM,
retrieve market data or use a broker.

## Implemented evidence contract

`AgentResult`, the external JSON bridge and paired research acceptance now
require or carry upstream version, strategy identity, instrument identity,
market cutoff, decision timestamp, provider/model lineage, configuration
fingerprint, provenance references, abstention/unavailable flags and
`RESEARCH_ONLY` status. Pair acceptance rejects mismatched cutoffs, missing
provenance, abstentions converted to HOLD, stale/incompatible instruments and
malformed lineage. BUY/SELL/HOLD remain research conclusions and never create
orders or sizing.

TradingAgents' genuine graph constructor and propagation interface were
verified by import/signature inspection only. The graph was not executed.
BuffettAgent's genuine v2 interface was verified by import/signature inspection
only. It was not executed. No synthetic decision is presented as real research.

## Remaining blockers and owner action

- Paid/provider research is not authorized; do not run either bridge against a
  model provider yet.
- AI Hedge Fund requires a permitted model provider. Financial Datasets is no
  longer required when local SEC fundamentals are supplied, and the upstream
  identity is now pinned (`aihf==2.5.0+git.ec02537…`). SOFI SEC coverage is
  still insufficient; see `M2_BUFFETT_DATA_COMPATIBILITY.md`.
- A future owner-approved SOFI research run must use the isolated interpreters,
  an explicitly selected provider/model, independent genuine market/fundamental
  evidence, and produce two enriched `RESEARCH_ONLY` records for the paired
  gate.
- No eToro, Saxo or Alpaca request is part of this verification.
