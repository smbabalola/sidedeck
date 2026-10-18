# Integration licensing decision

Date: 2026-10-18

- `TauricResearch/TradingAgents` is treated as the licensed upstream reference at pinned commit `e8f5503e9b86d5c2710b0c76b1f686703968c9df`. Its observed public interface is `TradingAgentsGraph(...).propagate(ticker, trade_date)`, returning `(state, decision)`. SideDeck implements an injected, proposal-only boundary and does not vendor or execute the upstream package.
- `imranpollob/ai-trading` remains blocked. No licence permission has been established for copying, installing, importing or running its source. SideDeck's independent protocol fixture is not that upstream system.
- No paid model credentials, external market-data credentials, broker credentials or eToro access were used.
