# P3 batch — read-only Alpaca groundwork

Scope: P2 audit migration, integrity and concurrent-write regression accepted by CI before branch creation. P3 implementation adds a typed, injectable, offline-only Alpaca response adapter for account identity, balances and positions. Tests use synthetic fixtures, and no transport implementation is supplied that can reach the network. The broker binding remains disabled.

Before actual Alpaca access: add a separately reviewed HTTPS-only GET transport; verify the correct SideDeck paper account against independently supplied expected account identity (never assume key name proves identity); protect credentials and logs; add timeout/retry/rate-limit controls, account/position reconciliation, audit logs, and integration tests. Paper order execution requires a separate gate and must not be implied by successful read-only access.

Live trading remains out of scope.

## Acceptance ledger

1. P0 docs and blueprint: accepted in repository notes.
2. P1 domain/accounting: CI verified.
3. P1 persistence/replay: CI verified.
4. P2 proposal gate: CI verified.
5. P2 risk controls: CI verified.
6. P2 audit persistence and race tests: CI verified.
7. P3 read-only parsing and injected transport: in progress.
8. P3 credential/account identification: not implemented.
9. P3 portfolio reconciliation: not implemented.
10. P4 paper execution, order lifecycle: not implemented.
11. P5 strategy integration: not implemented.
12. P6 backtesting and comparison: not implemented.
13. P7 paper automation: not implemented.

Progress uses equally weighted gates for transparency, not engineering effort or trading performance. P0–P7 scope excludes future real-money trading. Before P3 adapter CI: 6/13 = 46%. After P3 adapter CI passes: 7/13 = 54%. The distinction between implementation and CI acceptance must be maintained.
