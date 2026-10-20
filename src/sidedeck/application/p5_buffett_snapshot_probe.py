"""No-LLM probe of installed upstream Buffett snapshot against validated local JSON.

No provider factory, predict(), brokerage client, or network call is used.
"""
from __future__ import annotations

import argparse
import json
import traceback
from importlib import import_module
from typing import Any

from sidedeck.bridges.filed_fundamentals import LocalFiledDataClient, verified_fundamentals


def snapshot_probe(path: str, ticker: str, as_of: str) -> dict[str, Any]:
    records = verified_fundamentals(path, ticker, as_of)
    if len(records) < 4:
        raise ValueError("insufficient verified financial periods")
    module = import_module("hedge_fund.signals.buffett")
    cls = getattr(module, "BuffettAgent")
    # Construct with a non-callable LLM sentinel. Snapshot must not invoke it.
    # Normal __init__ sets required internal state such as _blind.
    import inspect
    signature = inspect.signature(cls.build_snapshot)
    snapshot = None
    try:
        class NoLLM:
            def __getattr__(self, name: str) -> Any:
                raise RuntimeError("LLM access forbidden during snapshot probe")

        agent = cls(llm=NoLLM())
        snapshot = agent.build_snapshot(ticker, as_of, LocalFiledDataClient(path))
    except Exception as exc:
        frames = traceback.extract_tb(exc.__traceback__)
        last = frames[-1] if frames else None
        return {
            "ticker": ticker, "as_of": as_of,
            "snapshot_contract": str(signature),
            "snapshot_status": "UNAVAILABLE",
            "error_type": type(exc).__name__,
            "error_detail": str(exc)[:300],
            "error_location": (f"{last.name}:{last.lineno}" if last else "unknown"),
            "approved": False, "buffett_ready": False,
            "broker_execution": "DISABLED",
        }
    dumped: Any = snapshot.model_dump(mode="json") if hasattr(snapshot, "model_dump") else repr(snapshot)
    return {
        "ticker": ticker, "as_of": as_of,
        "snapshot_contract": str(signature),
        "snapshot_status": "CONSTRUCTED_UNVERIFIED",
        "snapshot": dumped,
        "approved": False, "buffett_ready": False,
        "broker_execution": "DISABLED",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Buffett no-LLM snapshot compatibility test")
    parser.add_argument("--fundamentals-json", required=True)
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--as-of", required=True)
    args = parser.parse_args()
    result = snapshot_probe(args.fundamentals_json, args.ticker, args.as_of)
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
