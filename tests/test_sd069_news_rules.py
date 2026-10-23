"""SD-069 news rules produce risk flags only (synthetic items; nothing fetched)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from sidedeck.application import sd069_news_rules as news
from sidedeck.application.sd069_news_rules import (
    NewsItem, NewsRuleError, entry_risk_flags, is_moving, new_items, tag,
)

UTC = timezone.utc
NOW = datetime(2026, 10, 23, 13, 0, tzinfo=UTC)


def _item(i: str, title: str, *, source: str = "HEADLINE", hours: int = 1,
          tickers: tuple[str, ...] = ("TSLA",), items: tuple[str, ...] = ()) -> NewsItem:
    return NewsItem(i, source, NOW - timedelta(hours=hours), tickers, title, items)


def test_headlines_are_tagged_by_what_they_touch():
    t = tag(_item("a", "Tesla Q3 earnings beat; analyst raises price target"))
    assert t.tags == ("analyst", "earnings")
    assert tag(_item("b", "Trading halted pending news")).tags == ("halt",)
    assert tag(_item("c", "Nothing much happened")).tags == ()


def test_important_8k_items_are_flagged():
    t = tag(_item("d", "8-K", source="SEC_8K", items=("2.02", "9.01")))
    assert t.important_items == ("2.02",) and "earnings" in t.tags
    restated = tag(_item("e", "8-K", source="SEC_8K", items=("4.02",)))
    assert restated.important_items == ("4.02",) and restated.tags == ("risk",)


def test_new_items_are_newest_first_and_never_repeat():
    seen: set[str] = set()
    first = new_items([_item("x", "old", hours=5), _item("y", "new", hours=1)], seen)
    assert [t.item.item_id for t in first] == ["y", "x"]
    assert new_items([_item("x", "old", hours=5), _item("z", "newer", hours=0)], seen)[0] \
        .item.item_id == "z"
    assert len(new_items([_item("x", "old"), _item("y", "new")], seen)) == 0


def test_moving_threshold():
    assert is_moving(Decimal("103"), Decimal("100"))
    assert is_moving(Decimal("97"), Decimal("100"))
    assert not is_moving(Decimal("102.99"), Decimal("100"))
    with pytest.raises(NewsRuleError):
        is_moving(Decimal("1"), Decimal("0"))


def test_entry_risk_flags_block_earnings_halts_deals_and_risk_only():
    tagged = [tag(_item("a", "Tesla earnings tonight")),
              tag(_item("b", "Analyst upgrade for Tesla")),                  # not blocking
              tag(_item("c", "8-K", source="SEC_8K", items=("5.02",))),
              tag(_item("d", "NVDA halted", tickers=("NVDA",))),             # other ticker
              tag(_item("e", "Tesla recall", hours=30))]                     # outside window
    assert entry_risk_flags(tagged, "TSLA", NOW) == ("NEWS_EARNINGS", "SEC_8K_ITEM_5.02")
    assert entry_risk_flags(tagged, "NVDA", NOW) == ("NEWS_HALT",)


def test_future_dated_items_are_refused_as_look_ahead():
    future = tag(NewsItem("f", "HEADLINE", NOW + timedelta(minutes=1), ("TSLA",), "earnings"))
    with pytest.raises(NewsRuleError, match="look-ahead"):
        entry_risk_flags([future], "TSLA", NOW)


def test_item_validation():
    with pytest.raises(NewsRuleError, match="timezone"):
        NewsItem("a", "HEADLINE", datetime(2026, 10, 23), ("TSLA",), "x")
    with pytest.raises(NewsRuleError, match="2.02"):
        _item("a", "x", source="SEC_8K", items=("202",))
    with pytest.raises(NewsRuleError, match="only SEC"):
        _item("a", "x", items=("2.02",))
    with pytest.raises(NewsRuleError, match="source"):
        _item("a", "x", source="TWITTER")


def test_module_never_builds_research_signals_or_touches_the_network():
    import ast
    from pathlib import Path
    tree = ast.parse(Path(news.__file__).read_text(encoding="utf-8"))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    modules = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    modules |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert "ResearchSignal" not in names
    assert not {m.split(".")[0] for m in modules} & {"urllib", "http", "requests", "socket"}
