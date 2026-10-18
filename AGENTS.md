# SideDeck agent instructions

## Scope

This repository is a deterministic research and virtual-accounting foundation. Work only on the requested branch and preserve untracked local work, especially `.env` and `SideDeck-Blueprint/`.

## Safety invariants

- Never add credentials, API keys, account IDs, private keys, or real-money capabilities.
- Do not connect to eToro, submit orders, run external trading agents, or begin P2 without explicit authorization.
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
