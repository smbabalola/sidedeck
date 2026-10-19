"""Explicit, credential-safe loading of research API keys from a local dotenv file."""
from __future__ import annotations

import os
from pathlib import Path


_RESEARCH_KEYS = frozenset({
    "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY",
    "FINANCIAL_DATASETS_API_KEY", "ALPHA_VANTAGE_API_KEY",
    "OPENROUTER_API_KEY", "DEEPSEEK_API_KEY",
})


def import_research_env(path: str | Path) -> tuple[str, ...]:
    """Import only allowlisted research credentials; never overwrite process env.

    Supports simple single-line KEY=VALUE syntax and quotes, not shell expansion.
    Broker secrets and arbitrary variables are deliberately ignored.
    """
    read = Path(path).read_text(encoding="utf-8-sig")
    available: list[str] = []
    for raw in read.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.removeprefix("export ").strip()
        if key not in _RESEARCH_KEYS:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if not value or "\n" in value or "\r" in value:
            continue
        os.environ.setdefault(key, value)
        if os.environ.get(key):
            available.append(key)
    return tuple(sorted(set(available)))
