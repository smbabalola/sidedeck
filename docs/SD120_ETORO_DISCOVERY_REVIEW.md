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

## Consumed-run diagnostic follow-up

The owner-run authorization `sd120-etoro-5m-20261026123521` is consumed and must not be rerun.
Its three search failures were recorded only as `HTTPError`, so the historical report cannot
establish whether the cause was authentication, entitlement, endpoint routing or rate limiting.
The collector now records the numeric HTTP status and a bounded classification, and stops after
the first HTTP failure. The next authenticated action, if still needed, is a separately signed
single-GET diagnostic for the same v1 search endpoint; it is not authorized by this change.

## Fresh diagnostic package (not authorized)

Prepare a new SD-077 authorization with exactly one request:

- `GET https://public-api.etoro.com/api/v1/market-data/search?internalSymbolFull=AAPL`
- host `public-api.etoro.com`; method `GET`; retries `0`
- credentials: local `ETORO_API_KEY` and `ETORO_USER_KEY`, read only after signature verification
- no redirects, other symbols, coverage/candle/account/order endpoints or response-body logging
- output: numeric HTTP status, bounded classification, response SHA-256 and sanitized schema result

The owner should first inspect the eToro portal for Demo environment, key pairing, market-data
permission, expiry and IP restrictions. If that does not identify the cause, sign this one-request
scope in the existing `sidedeck-data-authorization` namespace and run it once through SD-077.
Do not reuse `sd120-etoro-5m-20261026123521`, its digest, signature, ledger budget or marker.

## Executable diagnostic (still not authorized or run)

The single-GET package is now executable through the existing SD-077 verifier and persistent
ledger. It is a distinct authorization shape (`max_requests=1`, AAPL only), so the consumed
nine-request authorization cannot validate against it. The command sequence is:

```powershell
Set-Location 'C:\Users\smbab\OneDrive\Documents\Projects\sidedeck\sidedeck'
\.venv\Scripts\python.exe -m sidedeck.application.sd120_etoro_five_minute diagnostic-draft `
  --out data\authorizations\sd120-aapl-diagnostic.json --owner-confirms-terms-reviewed
\.venv\Scripts\python.exe -m sidedeck.application.sd077_data_authorization `
  data\authorizations\sd120-aapl-diagnostic.json --out-dir data\authorizations
```

The second command prints the digest and the exact owner signing command. After the owner signs
the generated `.digest.payload` with the pinned SSH key, the one-shot launch is:

```powershell
\.venv\Scripts\python.exe -m sidedeck.application.sd120_etoro_five_minute diagnostic-run `
  --authorization data\authorizations\sd120-aapl-diagnostic.json `
  --signature data\authorizations\sd120-aapl-diagnostic.digest.payload.sig `
  --allowed-signers data\approval_allowed_signers `
  --ledger data\data-authorization-ledger.sqlite3 `
  --out-dir data\sd120-aapl-diagnostic
```

The run verifies signature, signer, expiry and scope before loading credentials; reserves one
GET, rejects redirects and records only numeric status, bounded classification, response hash and
sanitized schema evidence. It never records response bodies, headers, identifiers or secrets.
No fresh authorization, credential use or network request has occurred in this batch.
