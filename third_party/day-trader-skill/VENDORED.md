# Vendored: day-trader-skill 2.0.0 (MIT)

Upstream: https://github.com/Jakeschincariol/day-trader-skill — Copyright (c) 2026 Jake Schincariol,
MIT License (see `LICENSE`, unchanged).

Pinned commit `3d0f4ef6986f4984b7c6bd46f7ff4f87744c3abd` (2026-10-20, "The Trader skill v2:
11 day-trading skills"). Copied byte-for-byte on 2026-10-26 from the Claude Code plugin install
(`~/.claude/plugins/cache/day-trader-skill/day-trader-skill/2.0.0`), which was verified
identical to the local marketplace checkout at that commit with a clean git tree. Upstream's
own test suite (315 tests) passed on that copy.

**No file in this folder is modified by SideDeck.** SideDeck's adapter
(`src/sidedeck/modules/day_trader/`) verifies every script against pinned SHA-256 hashes before
use, runs scripts only in offline mode inside a network-blocked, credential-free sandbox, never
follows the SKILL.md instructions, and never forwards broker tickets to a broker connector.
