# SD-120 eToro discovery independent review

## Verdict

`VERIFIED_OFFLINE; AUTHENTICATED RUN NOT AUTHORIZED OR EXECUTED`.

The collector is separate from the eToro Demo trading transport and has no order, account,
portfolio, rates, cancel or write path. It uses only the public eToro host and GET requests after
SD-077 signature verification.

## Controls reviewed

- The canonical signature includes the host/path templates, three-symbol universe, fixed UTC
  window, interval, side, page limit, credential environment names, request sequence, expiry,
  zero retries and nine-request maximum.
- `ssh-keygen -Y verify` is performed before credential lookup; the pinned signer and namespace
  are checked first.
- The single-use authorization marker is claimed before the first request. The shared SQLite
  ledger reserves every request before transmission and cannot be reset by changing the output
  directory.
- HTTPS host allowlisting, exact endpoint templates, no redirects, GET-only method, response-size
  limits and sanitized output are enforced.
- Search results require one exact requested identity and a positive instrument ID. Coverage must
  match that ID and symbol. Candle pages accept `AAPL/USD`-style display names, allow `null` only
  on an empty page, normalize documented newest-first results, and reject duplicate or invalid
  OHLC values.
- `side=both` is canonicalized as separate bid and ask candles per timestamp; it is never merged
  into a synthetic mid-price series.
- Coverage failure or no five-minute coverage skips its dependent sample request. Errors consume
  their reserved request and are not retried.

## Residual boundaries

The package establishes neither entitlement nor data quality until the owner runs the signed
scope. A successful sample does not establish five-year history, corporate-action adjustment,
consolidated/SIP semantics, exchange-session completeness, volume meaning or strategy validity.
The Day Trader module remains `RESEARCH_ONLY`; broker execution remains disabled.
