# SideDeck P3 read-only Alpaca access

The paper-only HTTPS transport restricts requests to exact `GET /v2/account` and `GET /v2/positions` operations. It is opt-in: constructing a client does not contact Alpaca. It reads only SideDeck's `ALPACA_API_KEY2` and `ALPACA_API_SECRET_KEY2` at invocation and never exposes them in output. It refuses unknown endpoints, bounded timeouts, oversized JSON replies and errors without exposing server responses.

It is not yet authenticated against an actual Alpaca account. The expected Alpaca account UUID must be configured independently and compared to the returned identity. The application must then reconcile positions, account equity/cash and any pre-existing holdings before treating broker state as attributable to the two internal strategy portfolios.

Account balance reconciliation is not complete. The paper account may contain other holdings or capital: those must be excluded from strategy performance rather than silently absorbed. No order submission method is implemented and live trading remains prohibited. No automatic schedule has been enabled.

Deployment must ensure credentials live only in the intended SideDeck environment, never GitHub source, build logs, documentation or browser code.
