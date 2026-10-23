"""SD-093 offline UK SIMULATION order desk (no broker, no network, no credentials).

Every order, fill and position here is ``SIMULATION`` with fills labelled
``SIMULATED_LOCAL``. The desk exists to exercise the UK lifecycle end to end:

    normalized GBP quote -> pre-trade checks -> simulated order -> simulated venue
    execution -> fill -> position -> exit -> reconciliation

Design:

* One SQLite file per book. The book id must start with ``SIM_UK_`` and can never be
  a protected book (the eToro Demo baseline, the MSFT pilot, US track ledgers or
  Alpaca paper books). A file created for one book refuses another.
* Desk events are append-only. The simulated venue writes its own execution table.
  A crash between venue execution and desk recording is recovered by **lookup
  only** (``recover``); an order is never resubmitted.
* An outcome that cannot be established (venue lookup unavailable) becomes
  ``UNRESOLVED``, trips the kill-switch, and blocks further orders. The position is
  reported as possibly open; it is never silently assumed closed.
* Idempotency: an intent id can be used once. A repeat returns the original result.
* Prices are GBP (already normalized from GBX by SD-090). Quantities and money are
  ``Decimal``. UK stamp duty (SDRT) is modelled as a simulation assumption on
  purchases of ordinary shares; it is not broker evidence.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Mapping

from sidedeck.application.sd089_exchange_calendar import XLON, ExchangeCalendar
from sidedeck.application.sd090_uk_market import NormalizedQuote

OUTCOME_LABEL = "SIMULATION"
FILL_BASIS = "SIMULATED_LOCAL"
INTENT_SOURCES = frozenset({"STRATEGY_DECISION", "CONTROLLED_EXECUTION_FIXTURE"})
PROTECTED_BOOKS = frozenset({
    "ETORO_DEMO_BASELINE", "ETORO_DEMO_MSFT_PILOT", "US_DAY", "US_SWING", "US_POSITION",
    "DAY", "SWING", "POSITION", "ALPACA_PAPER_A", "ALPACA_PAPER_B",
})
TERMINAL = frozenset({"FILLED", "PARTIALLY_FILLED", "CANCELLED_UNFILLED", "REJECTED"})
ZERO = Decimal(0)
PENNY = Decimal("0.01")


class SimDeskError(ValueError):
    pass


class SimInterruption(RuntimeError):
    """Raised to simulate a process crash at a chosen point in the lifecycle."""


@dataclass(frozen=True)
class SimVenueMapping:
    canonical_id: str
    venue: str
    venue_instrument_id: str
    asset_type: str
    min_notional_gbp: Decimal
    quantity_step: Decimal

    def __post_init__(self) -> None:
        if not self.venue.startswith("SIDEDECK_SIM_"):
            raise SimDeskError("simulation mappings must name a SIDEDECK_SIM_ venue")
        if self.min_notional_gbp <= 0 or self.quantity_step <= 0:
            raise SimDeskError("invalid minimum order or quantity step")


@dataclass(frozen=True)
class UkOrderIntent:
    intent_id: str
    book_id: str
    canonical_id: str
    side: str
    quantity: Decimal
    limit_price_gbp: Decimal
    source: str
    created_at: datetime
    decision_status: str | None = None
    label: str = OUTCOME_LABEL

    def __post_init__(self) -> None:
        if self.label != OUTCOME_LABEL:
            raise SimDeskError("intents on this desk must be labelled SIMULATION")
        if self.source not in INTENT_SOURCES:
            raise SimDeskError("unknown intent source")
        if self.source == "STRATEGY_DECISION" and self.decision_status != "ELIGIBLE":
            raise SimDeskError("a strategy intent needs an ELIGIBLE decision")
        if self.side not in ("BUY", "SELL"):
            raise SimDeskError("side must be BUY or SELL")
        if not self.intent_id.strip():
            raise SimDeskError("intent id required")
        if self.created_at.tzinfo is None:
            raise SimDeskError("timezone-aware time required")
        for value in (self.quantity, self.limit_price_gbp):
            if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
                raise SimDeskError("quantity and limit must be positive Decimals")


@dataclass(frozen=True)
class FillPlan:
    """How the simulated venue behaves for one order (test and demo control)."""

    fill_ratio: Decimal = Decimal(1)        # (0, 1]; < 1 = partial IOC, remainder cancelled
    crash_after_venue: bool = False         # venue executes, desk crashes before recording
    venue_lookup_available: bool = True     # False = recovery cannot establish the outcome

    def __post_init__(self) -> None:
        if not ZERO < self.fill_ratio <= 1:
            raise SimDeskError("fill ratio must be in (0, 1]")


@dataclass(frozen=True)
class OrderResult:
    order_id: str
    intent_id: str
    status: str
    reason: str
    filled_quantity: Decimal
    avg_price_gbp: Decimal | None
    fees_gbp: Decimal
    label: str = OUTCOME_LABEL
    fill_basis: str = FILL_BASIS


@dataclass(frozen=True)
class PositionView:
    canonical_id: str
    quantity: Decimal
    avg_cost_gbp: Decimal
    status: str  # OPEN | MAY_BE_OPEN_UNRESOLVED


@dataclass(frozen=True)
class Reconciliation:
    status: str  # MATCHED | MISMATCH | UNRESOLVED
    cash_gbp: Decimal
    realized_pnl_gbp: Decimal
    fees_gbp: Decimal
    positions: tuple[PositionView, ...]
    venue_quantity: Mapping[str, Decimal]
    issues: tuple[str, ...]
    label: str = OUTCOME_LABEL


def _q(value: Decimal) -> Decimal:
    return value.quantize(PENNY, rounding=ROUND_HALF_UP)


class UkSimDesk:
    def __init__(
        self,
        path: Path,
        *,
        book_id: str,
        capital_gbp: Decimal,
        mappings: Mapping[str, SimVenueMapping],
        calendar: ExchangeCalendar = XLON,
        max_quote_age: timedelta = timedelta(seconds=60),
        stamp_duty_rate: Decimal = Decimal("0.005"),
        commission_gbp: Decimal = ZERO,
    ) -> None:
        if book_id in PROTECTED_BOOKS or not book_id.startswith("SIM_UK_"):
            raise SimDeskError("PROTECTED_OR_NON_SIMULATION_BOOK")
        if capital_gbp <= 0 or stamp_duty_rate < 0 or commission_gbp < 0:
            raise SimDeskError("invalid capital or fee assumptions")
        self._path = path
        self.book_id = book_id
        self.capital = capital_gbp
        self.mappings = dict(mappings)
        self.calendar = calendar
        self.max_quote_age = max_quote_age
        self.stamp_duty_rate = stamp_duty_rate
        self.commission = commission_gbp
        with closing(self._conn()) as conn:
            foreign = {
                str(row[0]) for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            } - {"meta", "events", "venue_executions"}
            if foreign:
                raise SimDeskError("FILE_IS_NOT_A_UK_SIMULATION_BOOK")
            conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY AUTOINCREMENT,"
                " at TEXT, kind TEXT, order_id TEXT, payload TEXT)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS venue_executions (order_id TEXT PRIMARY KEY,"
                " canonical_id TEXT, side TEXT, quantity TEXT, price TEXT, at TEXT)"
            )
            conn.execute(
                "CREATE TRIGGER IF NOT EXISTS events_append_only BEFORE UPDATE ON events "
                "BEGIN SELECT RAISE(ABORT, 'events are append-only'); END"
            )
            conn.execute(
                "CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events "
                "BEGIN SELECT RAISE(ABORT, 'events are append-only'); END"
            )
            row = conn.execute("SELECT value FROM meta WHERE key='book'").fetchone()
            if row is None:
                conn.execute("INSERT INTO meta VALUES ('book', ?)", (book_id,))
                conn.execute("INSERT INTO meta VALUES ('capital', ?)", (str(capital_gbp),))
            elif row[0] != book_id:
                raise SimDeskError("BOOK_FILE_BELONGS_TO_ANOTHER_BOOK")

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path, isolation_level=None)

    # --- event log ----------------------------------------------------------------------
    def _append(self, conn: sqlite3.Connection, at: datetime, kind: str, order_id: str,
                payload: dict[str, Any]) -> None:
        body = {**payload, "label": OUTCOME_LABEL}
        conn.execute("INSERT INTO events (at, kind, order_id, payload) VALUES (?,?,?,?)",
                     (at.astimezone(UTC).isoformat(), kind, order_id,
                      json.dumps(body, sort_keys=True, default=str)))

    def events(self) -> tuple[tuple[str, str, dict[str, Any]], ...]:
        with closing(self._conn()) as conn:
            rows = conn.execute("SELECT kind, order_id, payload FROM events ORDER BY seq").fetchall()
        return tuple((str(k), str(o), json.loads(p)) for k, o, p in rows)

    def _order_states(self) -> dict[str, dict[str, Any]]:
        states: dict[str, dict[str, Any]] = {}
        for kind, oid, payload in self.events():
            state = states.setdefault(oid, {"order_id": oid})
            state.update(payload)
            state["status"] = kind
        return states

    @property
    def kill_switch(self) -> bool:
        return any(kind == "KILL_SWITCH_TRIPPED" for kind, _, _ in self.events())

    # --- accounting (replayed from desk events only) -------------------------------------
    def _book(self) -> tuple[Decimal, Decimal, Decimal, dict[str, tuple[Decimal, Decimal]]]:
        cash, realized, fees = self.capital, ZERO, ZERO
        positions: dict[str, tuple[Decimal, Decimal]] = {}
        for kind, _, p in self.events():
            if kind not in ("FILLED", "PARTIALLY_FILLED"):
                continue
            qty, price, fee = Decimal(p["filled_quantity"]), Decimal(p["avg_price_gbp"]), \
                Decimal(p["fees_gbp"])
            cid = p["canonical_id"]
            held, cost = positions.get(cid, (ZERO, ZERO))
            fees += fee
            if p["side"] == "BUY":
                # Purchase fees (stamp duty, commission) are part of the cost basis, so a
                # closed round trip's realized P&L equals its cash change.
                cash -= _q(qty * price) + fee
                positions[cid] = (held + qty, cost + _q(qty * price) + fee)
            else:
                # Cost released pro rata; the last unit releases the exact remainder.
                released = cost if qty == held else _q(cost * qty / held)
                cash += _q(qty * price) - fee
                realized += _q(qty * price) - fee - released
                positions[cid] = (held - qty, cost - released)
        return cash, realized, fees, positions

    # --- order flow ------------------------------------------------------------------
    def _reject(self, intent: UkOrderIntent, now: datetime, reason: str) -> OrderResult:
        order_id = f"{self.book_id}:{intent.intent_id}"
        with closing(self._conn()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._append(conn, now, "REJECTED", order_id, {
                "intent_id": intent.intent_id, "canonical_id": intent.canonical_id,
                "side": intent.side, "reason": reason, "source": intent.source,
                "fingerprint": self._fingerprint(intent),
            })
            conn.execute("COMMIT")
        return OrderResult(order_id, intent.intent_id, "REJECTED", reason, ZERO, None, ZERO)

    @staticmethod
    def _fingerprint(intent: UkOrderIntent) -> str:
        text = "|".join((intent.book_id, intent.canonical_id, intent.side, str(intent.quantity),
                         str(intent.limit_price_gbp), intent.source))
        return hashlib.sha256(text.encode()).hexdigest()

    def _existing(self, intent: UkOrderIntent) -> OrderResult | None:
        intent_id = intent.intent_id
        state = self._order_states().get(f"{self.book_id}:{intent_id}")
        if state is None:
            return None
        if state.get("fingerprint", self._fingerprint(intent)) != self._fingerprint(intent):
            return OrderResult(state["order_id"], intent_id, "REJECTED",
                               "INTENT_ID_REUSED_WITH_DIFFERENT_PARAMS", ZERO, None, ZERO)
        return OrderResult(
            state["order_id"], intent_id, state["status"],
            "DUPLICATE_INTENT_ORIGINAL_RESULT", Decimal(state.get("filled_quantity", "0")),
            Decimal(state["avg_price_gbp"]) if state.get("avg_price_gbp") else None,
            Decimal(state.get("fees_gbp", "0")),
        )

    def submit(self, intent: UkOrderIntent, quote: NormalizedQuote, now: datetime, *,
               plan: FillPlan = FillPlan()) -> OrderResult:
        if now.tzinfo is None:
            raise SimDeskError("timezone-aware time required")
        existing = self._existing(intent)
        if existing is not None:
            return existing
        reason = self._pre_trade(intent, quote, now)
        if reason is not None:
            return self._reject(intent, now, reason)
        mapping = self.mappings[intent.canonical_id]
        order_id = f"{self.book_id}:{intent.intent_id}"
        price = quote.ask if intent.side == "BUY" else quote.bid
        filled = (intent.quantity * plan.fill_ratio / mapping.quantity_step).to_integral_value(
            rounding=ROUND_FLOOR) * mapping.quantity_step
        with closing(self._conn()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            # Re-check under the write lock so two processes cannot both submit.
            racing = conn.execute(
                "SELECT order_id, kind FROM events WHERE seq IN "
                "(SELECT MAX(seq) FROM events WHERE order_id != 'desk' GROUP BY order_id)"
            ).fetchall()
            if any(o == order_id for o, _ in racing) or any(k == "SUBMITTED" for _, k in racing):
                conn.execute("ROLLBACK")
                return OrderResult(order_id, intent.intent_id, "REJECTED",
                                   "CONCURRENT_SUBMISSION_REFUSED", ZERO, None, ZERO)
            self._append(conn, now, "SUBMITTED", order_id, {
                "fingerprint": self._fingerprint(intent),
                "intent_id": intent.intent_id, "canonical_id": intent.canonical_id,
                "side": intent.side, "quantity": str(intent.quantity),
                "limit_price_gbp": str(intent.limit_price_gbp), "source": intent.source,
                "venue": mapping.venue, "venue_instrument_id": mapping.venue_instrument_id,
                "quote_source": quote.source_id, "quote_basis": quote.data_basis,
                "quote_time": quote.quoted_at.isoformat(), "quote_unit": quote.source_unit,
                "lookup_available": plan.venue_lookup_available,
            })
            conn.execute("COMMIT")
        # --- simulated venue: executes and records independently of the desk ---------
        if filled > 0:
            with closing(self._conn()) as conn:
                conn.execute("INSERT INTO venue_executions VALUES (?,?,?,?,?,?)",
                             (order_id, intent.canonical_id, intent.side, str(filled), str(price),
                              now.astimezone(UTC).isoformat()))
        if plan.crash_after_venue:
            raise SimInterruption("simulated crash after venue execution, before desk record")
        return self._record_fill(order_id, intent.canonical_id, intent.side, intent.quantity,
                                 filled, price, mapping, now)

    def _fees(self, side: str, qty: Decimal, price: Decimal, mapping: SimVenueMapping) -> Decimal:
        duty = self.stamp_duty_rate if side == "BUY" and mapping.asset_type == "COMMON_STOCK" \
            else ZERO
        return _q(qty * price * duty) + self.commission

    def _record_fill(self, order_id: str, cid: str, side: str, ordered: Decimal, filled: Decimal,
                     price: Decimal, mapping: SimVenueMapping, now: datetime) -> OrderResult:
        intent_id = order_id.split(":", 1)[1]
        if filled == 0:
            kind, fee = "CANCELLED_UNFILLED", ZERO
        else:
            kind = "FILLED" if filled == ordered else "PARTIALLY_FILLED"
            fee = self._fees(side, filled, price, mapping)
        with closing(self._conn()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._append(conn, now, kind, order_id, {
                "intent_id": intent_id, "canonical_id": cid, "side": side,
                "filled_quantity": str(filled), "avg_price_gbp": str(price) if filled else "",
                "fees_gbp": str(fee), "fill_basis": FILL_BASIS,
                "remainder_cancelled": str(ordered - filled),
            })
            conn.execute("COMMIT")
        return OrderResult(order_id, intent_id, kind, "OK", filled, price if filled else None, fee)

    def _pre_trade(self, intent: UkOrderIntent, quote: NormalizedQuote, now: datetime) -> str | None:
        if self.kill_switch:
            return "KILL_SWITCH_ACTIVE"
        if intent.book_id != self.book_id:
            return "BOOK_MISMATCH_PROTECTED_SEPARATION"
        mapping = self.mappings.get(intent.canonical_id)
        if mapping is None:
            return "MISSING_VENUE_MAPPING"
        if quote.canonical_id != intent.canonical_id:
            return "QUOTE_INSTRUMENT_MISMATCH"
        if quote.price_unit != "GBP":
            return "QUOTE_NOT_NORMALIZED_TO_GBP"
        if quote.quoted_at > now:
            return "FUTURE_QUOTE"
        if now - quote.quoted_at > self.max_quote_age:
            return "STALE_QUOTE"
        if not self.calendar.is_open(now):
            return "MARKET_CLOSED"
        if (intent.quantity / mapping.quantity_step) % 1 != 0:
            return "QUANTITY_NOT_A_MULTIPLE_OF_STEP"
        if any(state.get("status") == "SUBMITTED" for state in self._order_states().values()):
            return "PRIOR_ORDER_OUTCOME_PENDING"
        price = quote.ask if intent.side == "BUY" else quote.bid
        if intent.side == "BUY" and intent.limit_price_gbp < quote.ask:
            return "LIMIT_BELOW_ASK_NOT_MARKETABLE"
        if intent.side == "SELL" and intent.limit_price_gbp > quote.bid:
            return "LIMIT_ABOVE_BID_NOT_MARKETABLE"
        notional = intent.quantity * price
        if notional < mapping.min_notional_gbp:
            return "BELOW_MINIMUM_ORDER"
        cash, _, _, positions = self._book()
        if intent.side == "BUY" and notional + self._fees("BUY", intent.quantity, price,
                                                           mapping) > cash:
            return "INSUFFICIENT_SIM_CASH"
        if intent.side == "SELL" and intent.quantity > positions.get(intent.canonical_id,
                                                                    (ZERO, ZERO))[0]:
            return "SELL_EXCEEDS_SIM_POSITION"
        return None

    # --- recovery and reconciliation ---------------------------------------------------
    def recover(self, now: datetime) -> tuple[OrderResult, ...]:
        """Resolve SUBMITTED orders by venue lookup only. Never resubmits."""
        results: list[OrderResult] = []
        for oid, state in self._order_states().items():
            if state.get("status") != "SUBMITTED":
                continue
            mapping = self.mappings.get(state["canonical_id"])
            if not state.get("lookup_available", True) or mapping is None:
                with closing(self._conn()) as conn:
                    conn.execute("BEGIN IMMEDIATE")
                    self._append(conn, now, "UNRESOLVED", oid, {
                        "canonical_id": state["canonical_id"], "side": state["side"],
                        "reason": "VENUE_OUTCOME_UNKNOWN",
                    })
                    self._append(conn, now, "KILL_SWITCH_TRIPPED", "desk",
                                 {"reason": f"unresolved order {oid}"})
                    conn.execute("COMMIT")
                results.append(OrderResult(oid, state["intent_id"], "UNRESOLVED",
                                           "VENUE_OUTCOME_UNKNOWN", ZERO, None, ZERO))
                continue
            with closing(self._conn()) as conn:
                row = conn.execute(
                    "SELECT quantity, price FROM venue_executions WHERE order_id=?", (oid,)
                ).fetchone()
            filled, price = (Decimal(row[0]), Decimal(row[1])) if row else (ZERO, ZERO)
            results.append(self._record_fill(oid, state["canonical_id"], state["side"],
                                             Decimal(state["quantity"]), filled, price, mapping,
                                             now))
        return tuple(results)

    def reconcile(self) -> Reconciliation:
        cash, realized, fees, positions = self._book()
        states = self._order_states()
        unresolved = {s["canonical_id"] for s in states.values()
                      if s.get("status") in ("UNRESOLVED", "SUBMITTED")}
        with closing(self._conn()) as conn:
            rows = conn.execute(
                "SELECT order_id, canonical_id, side, quantity FROM venue_executions"
            ).fetchall()
        venue: dict[str, Decimal] = {}
        for _, cid, side, qty in rows:
            venue[cid] = venue.get(cid, ZERO) + (Decimal(qty) if side == "BUY" else -Decimal(qty))
        issues: list[str] = []
        views: list[PositionView] = []
        for cid in sorted(set(positions) | set(venue) | unresolved):
            held = positions.get(cid, (ZERO, ZERO))
            if cid in unresolved:
                issues.append(f"{cid}:UNRESOLVED_ORDER")
            elif held[0] != venue.get(cid, ZERO):
                issues.append(f"{cid}:DESK_{held[0]}_VS_VENUE_{venue.get(cid, ZERO)}")
            if held[0] != 0 or cid in unresolved:
                views.append(PositionView(
                    cid, held[0], _q(held[1] / held[0]) if held[0] else ZERO,
                    "MAY_BE_OPEN_UNRESOLVED" if cid in unresolved else "OPEN",
                ))
        status = "UNRESOLVED" if unresolved or self.kill_switch else (
            "MISMATCH" if issues else "MATCHED")
        return Reconciliation(status, cash, realized, fees, tuple(views), venue, tuple(issues))
