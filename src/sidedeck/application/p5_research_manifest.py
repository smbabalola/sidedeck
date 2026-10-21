"""Hash-only research input manifests; no raw evidence or credentials are emitted."""
from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any


def build_input_manifest(*, ticker: str, as_of: date, sources: list[dict[str, Any]]) -> dict[str, Any]:
    if not ticker or not sources:
        raise ValueError("ticker and evidence sources are required")
    safe: list[dict[str, str]] = []
    for source in sources:
        if not isinstance(source, dict) or not isinstance(source.get("source"), str):
            raise ValueError("each source needs a label")
        content = source.get("content")
        if not isinstance(content, (dict, list, str, int, float, bool, type(None))):
            raise ValueError("source content is not JSON-compatible")
        encoded = json.dumps(content, sort_keys=True, separators=(",", ":"), default=str).encode()
        safe.append({"source": source["source"], "sha256": hashlib.sha256(encoded).hexdigest()})
    return {"schema_version": 1, "ticker": ticker, "as_of": as_of.isoformat(),
            "sources": sorted(safe, key=lambda item: item["source"]),
            "valuation": "BLOCKED_UNTIL_INDEPENDENT_PRICE_EVIDENCE",
            "broker_execution": "DISABLED"}
