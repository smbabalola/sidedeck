# SideDeck agent instructions

## Mandatory steering / self-directed work

Read [SIDEDECK_STEERING.md](SIDEDECK_STEERING.md) **before** selecting tasks. It is the durable engineering mandate and governs the live execution board at the top of [TODO.md](TODO.md). Continue coordinated, offline-safe, tested development batches without requiring one new owner instruction per task. Update TODO as work proceeds; stop only actions requiring specific external access/spend/trading authorization under the steering charter. Preserve stricter safety conditions in this file. Never infer authorization from the existence of credentials.


## Scope

This repository is a deterministic research and virtual-accounting foundation. Work only on the requested branch and preserve untracked local work, especially `.env` and `SideDeck-Blueprint/`.

## Safety invariants

- Never add credentials, API keys, account IDs, private keys, or real-money capabilities.
- Do not make new authenticated broker GET requests, submit orders, or execute paid external agent/provider research without the specific separate owner authorization defined in SIDEDECK_STEERING.md. Earlier one-shot owner-approved reads do not grant ongoing permissions.
- Do not connect to an existing user database. PostgreSQL tests must use a disposable CI/container database or remain explicitly unverified.
- Keep agent outputs proposal-only. SideDeck owns validation, risk, execution simulation, and accounting.
- Use `Decimal` for money/prices/quantities and timezone-aware UTC timestamps.
- Reject stale, future-dated, missing, unsupported, or economically inconsistent data/events.

## Verification

Before handoff, run the isolated project commands:

```powershell
.venv\Scripts\python.exe -m pytest
.venv\Scripts\ruff.exe check .
.venv\Scripts\mypy.exe src --no-incremental --follow-imports=silent
.venv\Scripts\python.exe -m alembic upgrade head
```

Report PostgreSQL upgrade/downgrade evidence separately from SQLite evidence.
