# SD-029 isolated paper-release rehearsal

Status: `VERIFIED` as an offline rehearsal only. It is not a paper-order
release, broker acceptance, or owner approval.

`sd029_operator_rehearsal.py` provides a disposable in-memory desk with no
HTTP transport, credentials, account state or broker client. The rehearsal
covers:

1. proposal intent with portfolio/instrument/client-order identity;
2. explicit external human approval record and rejection of system/strategy
   self-approval;
3. simulated submission and acknowledgement;
4. partial-fill then full-fill transitions;
5. exit attribution and append-only event lineage;
6. idempotency replay and conflicting client-order rejection;
7. fill rollback, recovery semantics and emergency-stop blocking.

The result is `REHEARSED`, while `broker_execution=DISABLED`. The tests are
local fixtures only and do not establish account mapping, broker reconciliation,
cryptographic signing, or permission to submit paper orders. SD-011 and SD-013
remain blocked pending separate owner release and operational evidence.
