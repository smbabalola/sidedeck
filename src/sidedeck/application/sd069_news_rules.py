"""SD-069 native news rules: event-risk flags, never signals (offline, deterministic).

Methodology attribution: the tagging, important-8-K and MOVING rules follow the MIT-licensed
``day-trader-skill`` 2.0.0 ``trader-news`` documentation (Copyright (c) 2026 Jake Schincariol).
No code from that package runs here, nothing is fetched, and no LLM reads stories at runtime.

Per that documentation, headlines are leads, not facts, and the monitor never predicts. So this
module only turns already-collected items (headlines or SEC 8-K entries, supplied by an approved
collector) into **risk flags** that can block a new entry or be passed to the SD-067 scanner as
event flags. It never produces a ``ResearchSignal`` and never says what a stock will do.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Iterable, Sequence

TAG_KEYWORDS: dict[str, tuple[str, ...]] = {
    "earnings": ("earnings", "quarterly results", "eps", "revenue", "guidance"),
    "analyst": ("upgrade", "downgrade", "price target", "analyst", "initiates coverage"),
    "legal": ("lawsuit", "sues", "sued", "settlement", "probe", "investigation"),
    "deal": ("acquire", "acquisition", "merger", "buyout", "takeover"),
    "capital": ("offering", "buyback", "repurchase", "dividend", "convertible"),
    "people": ("ceo", "cfo", "resigns", "steps down", "appoints", "names new"),
    "risk": ("recall", "bankruptcy", "default", "delist", "going concern", "restate"),
    "halt": ("halt", "halted", "trading pause"),
    "regulatory": ("fda", "sec charges", "ftc", "doj", "antitrust", "approval"),
    "macro": ("federal reserve", "fed ", "cpi", "jobs report", "tariff", "rate decision"),
}
IMPORTANT_8K_ITEMS: dict[str, str] = {
    "2.02": "earnings", "5.02": "people", "2.06": "risk", "3.01": "risk",
    "4.02": "risk", "1.03": "risk", "1.05": "risk",
}
BLOCKING_TAGS = frozenset({"earnings", "halt", "risk", "deal"})
DEFAULT_MOVE_PCT = Decimal("3")
_ITEM = re.compile(r"[1-9]\.[0-9]{2}")


class NewsRuleError(ValueError):
    pass


@dataclass(frozen=True)
class NewsItem:
    item_id: str
    source: str                       # HEADLINE | SEC_8K
    published_at: datetime
    tickers: tuple[str, ...]
    title: str
    form_items: tuple[str, ...] = ()  # 8-K item numbers, e.g. ("2.02",)

    def __post_init__(self) -> None:
        if self.source not in ("HEADLINE", "SEC_8K"):
            raise NewsRuleError("source must be HEADLINE or SEC_8K")
        if self.published_at.tzinfo is None:
            raise NewsRuleError("timezone-aware time required")
        if not self.item_id.strip() or not self.tickers:
            raise NewsRuleError("item id and at least one ticker are required")
        if any(not _ITEM.fullmatch(i) for i in self.form_items):
            raise NewsRuleError("8-K items look like 2.02")
        if self.form_items and self.source != "SEC_8K":
            raise NewsRuleError("only SEC 8-K items carry form items")


@dataclass(frozen=True)
class TaggedItem:
    item: NewsItem
    tags: tuple[str, ...]
    important_items: tuple[str, ...]   # the `!` items of the documentation


def tag(item: NewsItem) -> TaggedItem:
    title = f" {item.title.lower()} "
    tags = {name for name, words in TAG_KEYWORDS.items() if any(w in title for w in words)}
    important = tuple(sorted(i for i in item.form_items if i in IMPORTANT_8K_ITEMS))
    tags |= {IMPORTANT_8K_ITEMS[i] for i in important}
    return TaggedItem(item, tuple(sorted(tags)), important)


def new_items(items: Iterable[NewsItem], seen: set[str]) -> list[TaggedItem]:
    """Only what is new since the last check, newest first; never repeats an item."""
    fresh = [i for i in items if i.item_id not in seen]
    seen.update(i.item_id for i in fresh)
    return [tag(i) for i in sorted(fresh, key=lambda i: i.published_at, reverse=True)]


def is_moving(last: Decimal, previous_close: Decimal,
              pct: Decimal = DEFAULT_MOVE_PCT) -> bool:
    """MOVING: at least ``pct`` percent from yesterday's close, either way."""
    if not (last.is_finite() and previous_close.is_finite()) or previous_close <= 0 or last <= 0:
        raise NewsRuleError("prices must be positive and finite")
    return abs(last - previous_close) / previous_close * 100 >= pct


def entry_risk_flags(tagged: Sequence[TaggedItem], ticker: str, now: datetime,
                     lookback: timedelta = timedelta(hours=24)) -> tuple[str, ...]:
    """Flags that should block a *new* entry in ``ticker``: earnings, halts, deals and risk
    events published in the lookback window, plus every important 8-K item. Items dated in
    the future are refused (no look-ahead)."""
    if now.tzinfo is None:
        raise NewsRuleError("timezone-aware time required")
    flags: set[str] = set()
    for t in tagged:
        if ticker not in t.item.tickers:
            continue
        if t.item.published_at > now:
            raise NewsRuleError("news item dated after the evaluation time (look-ahead)")
        if now - t.item.published_at > lookback:
            continue
        flags |= {f"NEWS_{name.upper()}" for name in t.tags if name in BLOCKING_TAGS}
        flags |= {f"SEC_8K_ITEM_{i}" for i in t.important_items}
    return tuple(sorted(flags))
