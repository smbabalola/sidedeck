"""Command-line preview of staged TradingView execution CSV; no ledger writes."""
from __future__ import annotations

import argparse
from sidedeck.application.tradingview_import import import_tradingview_csv


def main() -> int:
    parser = argparse.ArgumentParser(description="Review normalized TradingView fills, no execution")
    parser.add_argument("csv_file")
    parser.add_argument("--portfolio", required=True, choices=["tradingagents", "ai-trading"])
    args = parser.parse_args()
    try:
        report = import_tradingview_csv(args.csv_file, portfolio_id=args.portfolio)
    except (OSError, ValueError, UnicodeError) as exc:
        print(f"BLOCKED: {type(exc).__name__}: {exc}")
        return 2
    print(f"STAGED ONLY: {len(report.fills)} fills; {report.ignored_unfilled} nonfills ignored; "
          f"{report.duplicate_rows} duplicate executions ignored")
    print(f"Portfolio: {args.portfolio}; source SHA256: {report.source_sha256}")
    print("No ledger modified, no simulated trades executed, no broker orders placed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
