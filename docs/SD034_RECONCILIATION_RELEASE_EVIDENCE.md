# SD-034 reconciliation and release evidence

The mock-only reconciliation contract accepts acknowledgement, partial/full
fills and exits while detecting duplicate events, missing or out-of-order
sequence numbers, invalid transitions, negative quantities and exits beyond
filled quantity. It emits only local attribution evidence and always labels
broker execution `DISABLED`.

The dormant Alpaca proposal specifies at most three read-only identity,
position and open-order GETs, no paid calls, local-only credentials, no logged
account IDs and no order operation. It was not executed. A future request
requires a new bounded owner authorization. SD-004, account mapping,
reconciliation and paper-release gates remain unresolved; no P4 release is
inferred or merged.
