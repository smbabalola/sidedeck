# P5 — AI Agent Research Adapter Integration

Branch: `feat/p5-agent-adapters`. **Research-only / no broker execution**.

## Verified upstreams

- [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents): Apache-2.0; uses `TradingAgentsGraph.propagate(ticker, date)`. The bridge calls the genuine graph only if it is separately installed in an isolated Python environment. Upstream may require LLM/market-data credentials and incur costs.
- [virattt/ai-hedge-fund](https://github.com/virattt/ai-hedge-fund): MIT; latest public README documents interactive `aihf` and its internal paper ledger, **not a verified stable machine-readable decision API**. We do not call its internal paper trading or silently parse human-facing console text. A separate reviewed JSON research bridge is required.

The adapters pass only allowlisted research/LLM environment variables (never broker credentials). SideDeck owns the typed `TradeIntent` contract; an accepted research output is not an order. BUY/SELL require explicitly sized, validated `TradeIntent` values. No upstream agent receives Saxo/Alpaca/eToro credentials through this launcher.

## Current level of acceptance

| Gate | State |
|---|---|
| Agent subprocess isolation / broker-secret filtering | Implemented; CI tests required |
| TradingAgents Python research bridge | Implemented, not authenticated/run against upstream |
| AI Hedge Fund runtime bridge | Contract only — needs verified non-executing API |
| SideDeck `TradeIntent` normalization | Implemented, proposal-only |
| Market/provider model calls | Not run; keys and model spend not authorized in this batch |
| SideDeck proposal/risk orchestration | Not yet wired to agent launcher |
| Research decision persistence / fair performance comparison | Not yet implemented |
| Saxo execution | DISABLED |

## Usage

Install official upstream TradingAgents separately in an isolated Python environment, then run its bridge in a context where `sidedeck` is installed, with explicit permitted research API credentials. The bridge outputs only a ticker/BUY-SELL-HOLD/rationale JSON object on success.

`python -m sidedeck.application.p5_agents --tradingagents-python PATH_TO_RESEARCH_PYTHON --hedge-fund-python PATH_TO_SEPARATE_PYTHON --hedge-fund-bridge PATH_TO_REVIEWED_JSON_BRIDGE`

The AI Hedge Fund bridge must output strict JSON `{"ticker":"SOFI","decision":"HOLD","rationale":"..."}` from the genuine investment research workflow. **Do not create a fake bridge that returns constant/synthetic decisions to claim operational acceptance**.

We intentionally do not install dependencies, read real keys, trigger paid model calls, or execute broker orders in CI. No autonomous scheduler exists in this branch. P5 is NO-GO for dual-agent live research until both real upstream interfaces and verified data/LLM providers are working.

## Design boundaries

Use one market cut-off and same instrument universe for both agents. Keep existing `tradingagents` and `ai-trading` ledger identities at USD 1,000 apiece. Do not infer trade size from an upstream BUY string; risk screen after source/quote validation. Maintain P4 SIM-only order submission disabled.
