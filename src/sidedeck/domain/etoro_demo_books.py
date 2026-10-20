"""eToro DEMO logical books, unattributed baseline and read-only reconciliation.

Three books on the one Demo account, isolated from Saxo SIM, Alpaca paper and
the research ledgers:

* ``etoro-demo:tradingagents`` and ``etoro-demo:ai-trading`` hold only
  positions opened by a SideDeck order recorded for that strategy
  (strategy -> order ID -> broker position ID);
* ``etoro-demo:unattributed`` holds the pre-existing baseline positions and
  anything unexplained. It never conceals a discrepancy.

Rules: identity is the broker ``positionID`` (never ticker or instrument);
no book receives capital until an audited owner decision; baseline positions
are read-only and can never be closed through SideDeck. Order execution does
not exist in this module.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from sidedeck.domain.etoro_demo import DemoPortfolioSnapshot, DemoPosition, Figure

TRADINGAGENTS_BOOK = "etoro-demo:tradingagents"
AI_TRADING_BOOK = "etoro-demo:ai-trading"
UNATTRIBUTED_BOOK = "etoro-demo:unattributed"
STRATEGY_BOOKS = {"tradingagents": TRADINGAGENTS_BOOK, "ai-trading": AI_TRADING_BOOK}
DEMO_BOOKS = (TRADINGAGENTS_BOOK, AI_TRADING_BOOK, UNATTRIBUTED_BOOK)
ALLOCATION_STATUS = "NOT_ALLOCATED: requires an audited owner decision and verified Demo funds"


class EtoroDemoBookError(ValueError):
    """An attribution or protection rule was violated; nothing changed."""


@dataclass(frozen=True)
class BaselinePosition:
    position_id: int
    instrument_id: int
    order_id: int | None
    is_buy: bool
    units: Decimal
    opened_at: datetime

    @classmethod
    def of(cls, position: DemoPosition) -> "BaselinePosition":
        return cls(position.position_id, position.instrument_id, position.order_id,
                   position.is_buy, position.units, position.opened_at)


@dataclass(frozen=True)
class OrderAttribution:
    """A SideDeck Demo order recorded for one strategy book (future order path only)."""

    order_id: int
    book_id: str


def book_for_strategy(strategy: str) -> str:
    try:
        return STRATEGY_BOOKS[strategy]
    except KeyError:
        raise EtoroDemoBookError("not a SideDeck strategy with an eToro Demo book") from None


def baseline_from(snapshot: DemoPortfolioSnapshot) -> tuple[BaselinePosition, ...]:
    """Every position open before SideDeck trades on Demo; all unattributed."""
    return tuple(BaselinePosition.of(p) for p in sorted(snapshot.positions,
                                                         key=lambda p: p.position_id))


def require_sidedeck_owned(position_id: int, *, baseline: Iterable[BaselinePosition],
                           attributions: Iterable[OrderAttribution],
                           snapshot: DemoPortfolioSnapshot) -> str:
    """Return the owning strategy book, or refuse (baseline, unknown or unattributed)."""
    if any(b.position_id == position_id for b in baseline):
        raise EtoroDemoBookError("baseline positions are read-only and never closed by SideDeck")
    position = next((p for p in snapshot.positions if p.position_id == position_id), None)
    if position is None:
        raise EtoroDemoBookError("position is not open in the Demo snapshot")
    owner = {a.order_id: a.book_id for a in attributions}.get(position.order_id or -1)
    if owner is None:
        raise EtoroDemoBookError("position has no SideDeck order attribution")
    return owner


@dataclass(frozen=True)
class BookView:
    book_id: str
    position_ids: tuple[int, ...]
    units_by_instrument: dict[int, Decimal]
    unrealized_pnl: Figure
    allocation_status: str = ALLOCATION_STATUS


@dataclass(frozen=True)
class DemoReconciliation:
    status: str                       # MATCHED | DISCREPANCY
    observed_at: datetime
    books: dict[str, BookView]
    discrepancies: tuple[str, ...] = ()
    available_cash_usd: Figure = field(default_factory=lambda: Figure(None, "UNAVAILABLE"))
    execution_enabled: bool = False   # this adapter is read-only by construction


def reconcile_demo(snapshot: DemoPortfolioSnapshot, *, baseline: Iterable[BaselinePosition],
                   attributions: Iterable[OrderAttribution], now: datetime) -> DemoReconciliation:
    """Read-only comparison of a fresh snapshot with the baseline and SideDeck attributions."""
    snapshot.require_fresh(now)
    baseline = tuple(baseline)
    owners: Mapping[int, str] = {a.order_id: a.book_id for a in attributions}
    if any(book not in STRATEGY_BOOKS.values() for book in owners.values()):
        raise EtoroDemoBookError("attributions may only name a strategy book")
    open_by_id = {p.position_id: p for p in snapshot.positions}
    discrepancies: list[str] = []
    members: dict[str, list[DemoPosition]] = {book: [] for book in DEMO_BOOKS}

    baseline_ids = set()
    for base in baseline:
        baseline_ids.add(base.position_id)
        current = open_by_id.get(base.position_id)
        if current is None:
            discrepancies.append(f"baseline position {base.position_id} is no longer open")
        elif BaselinePosition.of(current) != base:
            discrepancies.append(f"baseline position {base.position_id} changed outside SideDeck")
            members[UNATTRIBUTED_BOOK].append(current)
        else:
            members[UNATTRIBUTED_BOOK].append(current)
        if base.order_id is not None and base.order_id in owners:
            discrepancies.append(f"attributed order {base.order_id} belongs to a baseline position")

    for position in snapshot.positions:
        if position.position_id in baseline_ids:
            continue
        owner = owners.get(position.order_id or -1)
        if owner is None:
            members[UNATTRIBUTED_BOOK].append(position)
            discrepancies.append(f"position {position.position_id} has no SideDeck attribution")
        else:
            members[owner].append(position)

    for order in snapshot.pending_orders:
        if order.order_id is None or order.order_id not in owners:
            discrepancies.append(f"pending {order.collection} order is not a SideDeck order")
    if snapshot.mirror_count:
        discrepancies.append("copy/mirror positions are present and are not supported")

    books = {}
    for book, positions in members.items():
        units: dict[int, Decimal] = {}
        for position in positions:
            signed = position.units if position.is_buy else -position.units
            units[position.instrument_id] = units.get(position.instrument_id, Decimal("0")) + signed
        ordered = tuple(sorted(positions, key=lambda p: p.position_id))
        books[book] = BookView(book, tuple(p.position_id for p in ordered), units,
                               snapshot.unrealized_pnl(ordered))
    return DemoReconciliation("DISCREPANCY" if discrepancies else "MATCHED", snapshot.observed_at,
                              books, tuple(discrepancies),
                              snapshot.available_cash_usd())
