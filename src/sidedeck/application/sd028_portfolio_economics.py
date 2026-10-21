"""Deterministic offline joint SPY/QQQ price-only portfolio audit."""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from math import sqrt
from pathlib import Path
from typing import Any


def _series(path: str | Path, expected: str) -> dict[date, Decimal]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("ticker") != expected or payload.get("broker_execution", "DISABLED") != "DISABLED":
        raise ValueError("unexpected instrument or execution state")
    if payload.get("adjustment") != "split" or payload.get("feed") != "sip":
        raise ValueError("split-adjusted SIP bars are required")
    rows = payload.get("records")
    if not isinstance(rows, list) or not rows:
        raise ValueError("price records are required")
    result = {date.fromisoformat(str(row["date"])): Decimal(str(row["close"])) for row in rows}
    if len(result) != len(rows) or any(value <= 0 or not value.is_finite() for value in result.values()):
        raise ValueError("prices must be unique, positive and finite")
    return result


def _correlation(left: list[Decimal], right: list[Decimal]) -> Decimal:
    if len(left) != len(right) or len(left) < 2:
        raise ValueError("paired returns are required")
    x = [float(value) for value in left]
    y = [float(value) for value in right]
    mean_x, mean_y = sum(x) / len(x), sum(y) / len(y)
    cov = sum((a - mean_x) * (b - mean_y) for a, b in zip(x, y))
    var_x = sum((a - mean_x) ** 2 for a in x)
    var_y = sum((b - mean_y) ** 2 for b in y)
    if var_x == 0 or var_y == 0:
        raise ValueError("return series must vary")
    return Decimal(str(cov / sqrt(var_x * var_y)))


def audit_joint_portfolio(spy_path: str | Path, qqq_path: str | Path) -> dict[str, Any]:
    spy, qqq = _series(spy_path, "SPY"), _series(qqq_path, "QQQ")
    days = sorted(set(spy) & set(qqq))
    if len(days) < 2:
        raise ValueError("overlapping sessions are required")
    spy_returns = [spy[curr] / spy[prev] - 1 for prev, curr in zip(days, days[1:])]
    qqq_returns = [qqq[curr] / qqq[prev] - 1 for prev, curr in zip(days, days[1:])]
    portfolio = [Decimal("0.5") * a + Decimal("0.5") * b for a, b in zip(spy_returns, qqq_returns)]
    equity = Decimal("1")
    peak = equity
    max_drawdown = Decimal("0")
    for value in portfolio:
        equity *= 1 + value
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, (peak - equity) / peak)
    weighted_buy_hold = Decimal("0.5") * spy[days[-1]] / spy[days[0]] + Decimal("0.5") * qqq[days[-1]] / qqq[days[0]]
    return {
        "schema_version": 1,
        "instruments": ["SPY", "QQQ"],
        "sessions": len(days),
        "overlap_status": "VERIFIED" if len(days) == len(spy) == len(qqq) else "REVIEW_REQUIRED",
        "weights": {"SPY": "0.50", "QQQ": "0.50"},
        "cash_weight": "0.00",
        "gross_exposure": "1.00",
        "max_concentration": "0.50",
        "correlation": f"{_correlation(spy_returns, qqq_returns):.12f}",
        "portfolio_ending_equity": f"{equity:.12f}",
        "weighted_price_only_buy_hold_equity": f"{weighted_buy_hold:.12f}",
        "portfolio_return": f"{equity - 1:.12f}",
        "max_drawdown": f"{max_drawdown:.12f}",
        "transaction_costs": "NOT_APPLIED; NO_REBALANCE_EVENTS_IN_BUNDLE",
        "turnover": "NOT_APPLIED; REBALANCE_SCHEDULE_UNSPECIFIED",
        "regime_sensitivity": "NOT_ASSESSED",
        "research_only": True,
        "broker_execution": "DISABLED",
    }
