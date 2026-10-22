"""SD-036 offline eToro DEMO order desk: outbox, approvals, lineage, recovery, reconciliation.

eToro Demo is SideDeck's primary paper broker (owner decision 2026-10-21);
Alpaca PAPER is secondary. This desk is **offline only**:

* The only transport it accepts is one that declares ``offline_simulation=True``
  (``OfflineEtoroDemoSimulator``). No HTTP transport exists in SideDeck for
  Demo writes, and ``ETORO_DEMO_EXECUTION_RELEASE`` is ``NO_GO``.
* eToro Real is permanently excluded (``require_demo_route``).
* Every write is recorded write-ahead (outbox + lineage) before the transport
  is called. A lost response trips the kill-switch and is recovered **only** by
  ``orders:lookup?referenceId=...``; SideDeck never resubmits automatically.
* A position is SideDeck-owned only via verified lineage
  (referenceId -> orderId -> positionExecutions[].positionId, with
  ``openingData.orderId`` equal to the order). Baseline positions can never be
  claimed or closed. Ticker/instrument is never ownership evidence.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Protocol

from sidedeck.application.sd032_durable_paper_intent import DurablePaperIntentStore, PaperIntent
from sidedeck.application.sd033_approval_killswitch import ApprovalKillSwitch, intent_digest
from sidedeck.domain.etoro_demo import DemoPortfolioSnapshot, parse_demo_portfolio
from sidedeck.domain.etoro_demo_books import (
    STRATEGY_BOOKS, BaselinePosition, EtoroDemoBookError, OrderAttribution, reconcile_demo,
)
from sidedeck.domain.etoro_demo_orders import (
    DEMO_CLOSE_INFO_PATH, DEMO_OPEN_PATH, DEMO_ORDER_LOOKUP_PATH, DEMO_PNL_PATH,
    ETORO_REAL_EXECUTION,
    NO_FILL_TERMINAL, ZERO, CloseAcceptance, DemoCloseRequest, DemoOpenRequest,
    DemoOrderOutcome, EtoroDemoOrderError, parse_close_acceptance, parse_close_info,
    parse_open_acceptance, parse_order_lookup, require_demo_route,
)

ETORO_DEMO_EXECUTION_RELEASE = "NO_GO"
CLOSE_SETTLED_STATES = frozenset({"FILLED", "REJECTED", "CANCELED", "EXPIRED",
                                  "CANCELED_PARTIALLY_FILLED", "REJECTED_PARTIALLY_FILLED",
                                  "RECONCILED_NOT_EXECUTED", "RECONCILED_CLOSED_BY_SNAPSHOT",
                                  "RECONCILED_PARTIAL_BY_SNAPSHOT"})
DESK_OPERATOR = "sidedeck-etoro-demo-desk"
# Unresolved risks from docs/SD036_ETORO_DEMO_CONTRACT_REVIEW.md §6 (R4 mitigated by SD-037;
# R1 closed by SD-038: baseline MATCHED 4/4 on 2026-10-21).
# R2: Demo environment + Read/Write permission owner-confirmed 2026-10-21; IP whitelist,
# expiry owner-attested; write capability unverified. R9 owner-accepted (ADR-004).
ETORO_DEMO_OPEN_RISKS = ("R2_KEY_IP_EXPIRY_OWNER_ATTESTED_WRITE_UNVERIFIED",
                         "R3_CLOSE_LOOKUP_UNVERIFIED", "R5_NO_RELEASED_TRANSPORT",
                         "R6_LIVE_SCHEMA_UNVERIFIED", "R8_NO_CAPITAL_ALLOCATED")


def etoro_demo_status() -> dict[str, Any]:
    """Sanitized, code-derived broker status for release-gate surfaces. No IDs or values."""
    return {"broker_priority": "PRIMARY", "secondary_broker": "ALPACA_PAPER",
            "execution_release": ETORO_DEMO_EXECUTION_RELEASE,
            "real_execution": ETORO_REAL_EXECUTION, "transport": "OFFLINE_SIMULATOR_ONLY",
            "baseline": "PROTECTED_UNATTRIBUTED", "ownership": "VERIFIED_LINEAGE_ONLY",
            "agent_portfolios": "NOT_ADOPTED_PENDING_EVIDENCE",
            "open_risks": list(ETORO_DEMO_OPEN_RISKS),
            # Owner decision 2026-10-22 (ADR-004): single Demo Read/Write pair.
            "accepted_risks": ["R9_SHARED_DEMO_READ_WRITE_PAIR_OWNER_ACCEPTED"]}


class BrokerExecutionDisabled(PermissionError):
    """A non-simulated transport was offered; Demo execution is not released."""


class TransportOutcomeUnknown(RuntimeError):
    """The request may have reached the broker but no response was received."""


class TransportNotFound(RuntimeError):
    """The broker reports no such order (HTTP 404)."""


class EtoroDemoTransport(Protocol):
    offline_simulation: bool

    def send(self, method: str, path: str, *, reference_id: str,
             body: dict[str, Any] | None = None,
             query: dict[str, str] | None = None) -> Any: ...


@dataclass(frozen=True)
class DemoDeskPolicy:
    """Explicit owner-set limits. There is no default; no capital is implied."""

    max_order_notional_usd: Decimal
    allowed_instrument_ids: frozenset[int]
    max_open_positions_per_book: int

    def __post_init__(self) -> None:
        cap = self.max_order_notional_usd
        if not isinstance(cap, Decimal) or not cap.is_finite() or cap <= 0:
            raise EtoroDemoOrderError("max order notional must be a positive Decimal")
        if not self.allowed_instrument_ids or self.max_open_positions_per_book < 1:
            raise EtoroDemoOrderError("instrument allowlist and position cap are required")


# Documented eToro Demo quotas (requests, window seconds), shared per bucket.
RATE_LIMITS = {"write": (20, 60), "order_info": (60, 60), "portfolio": (60, 60)}
MAX_CLOCK_REGRESSION = timedelta(seconds=1)
# eToro documents orders:lookup for open orders; its use for close orders is unproven.
CLOSE_LOOKUP_RECOVERY = "NOT_VERIFIED"


def bucket_for(method: str, path: str) -> str:
    if method == "POST":
        return "write"
    return "portfolio" if path.endswith("/pnl") else "order_info"


class RateBudgetExceeded(EtoroDemoOrderError):
    """A documented eToro quota would be exceeded; nothing was sent. No automatic retry."""


class DemoRateBudget:
    """Restart-safe sliding-window budget. Refuses (never sleeps or retries) when exhausted."""

    def __init__(self, path: str, limits: dict[str, tuple[int, int]] | None = None) -> None:
        self._limits = dict(RATE_LIMITS if limits is None else limits)
        self._db = sqlite3.connect(Path(path), isolation_level=None)
        self._db.execute("CREATE TABLE IF NOT EXISTS etoro_demo_rate_events ("
                         "sequence INTEGER PRIMARY KEY AUTOINCREMENT, bucket TEXT NOT NULL, "
                         "at TEXT NOT NULL)")

    def close(self) -> None:
        self._db.close()

    def acquire(self, bucket: str, now: datetime | None = None) -> int:
        """Record one request in ``bucket``; return the remaining allowance."""
        if bucket not in self._limits:
            raise RateBudgetExceeded("unknown eToro rate bucket")
        moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        limit, window = self._limits[bucket]
        self._db.execute("BEGIN IMMEDIATE")
        try:
            latest = self._db.execute("SELECT MAX(at) FROM etoro_demo_rate_events").fetchone()[0]
            if latest is not None and moment < datetime.fromisoformat(latest) - MAX_CLOCK_REGRESSION:
                raise RateBudgetExceeded("clock moved backwards; budget refuses to guess")
            since = (moment - timedelta(seconds=window)).isoformat()
            used = self._db.execute("SELECT COUNT(*) FROM etoro_demo_rate_events "
                                    "WHERE bucket=? AND at>?", (bucket, since)).fetchone()[0]
            if used >= limit:
                raise RateBudgetExceeded(f"eToro {bucket} quota {limit}/{window}s exhausted")
            self._db.execute("INSERT INTO etoro_demo_rate_events(bucket, at) VALUES (?, ?)",
                             (bucket, moment.isoformat()))
            self._db.execute("COMMIT")
        except BaseException:
            if self._db.in_transaction:
                self._db.execute("ROLLBACK")
            raise
        return int(limit - used - 1)


def open_scope(book: str, request: DemoOpenRequest) -> str:
    return (f"etoro-demo:open:{book}:{request.instrument_id}:{request.units}:"
            f"{request.limit_rate}:{request.reference_id}")


def close_scope(book: str, request: DemoCloseRequest) -> str:
    units = "ALL" if request.units_to_deduct is None else str(request.units_to_deduct)
    return f"etoro-demo:close:{book}:{request.position_id}:{units}:{request.reference_id}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


_LINEAGE_DDL = """
CREATE TABLE IF NOT EXISTS etoro_demo_lineage_orders (
  reference_id TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('OPEN','CLOSE')),
  intent_id TEXT NOT NULL UNIQUE, book_id TEXT NOT NULL, instrument_id INTEGER NOT NULL,
  units TEXT, limit_rate TEXT, position_id INTEGER, order_id INTEGER UNIQUE,
  filled_units TEXT NOT NULL DEFAULT '0', state TEXT NOT NULL, updated_at TEXT NOT NULL,
  CHECK (book_id IN ('etoro-demo:tradingagents','etoro-demo:ai-trading'))
);
CREATE TABLE IF NOT EXISTS etoro_demo_owned_positions (
  position_id INTEGER PRIMARY KEY, reference_id TEXT NOT NULL, order_id INTEGER NOT NULL,
  book_id TEXT NOT NULL, instrument_id INTEGER NOT NULL, units TEXT NOT NULL,
  remaining_units TEXT NOT NULL, state TEXT NOT NULL, recorded_at TEXT NOT NULL,
  FOREIGN KEY(reference_id) REFERENCES etoro_demo_lineage_orders(reference_id)
);
"""


class EtoroDemoLineage:
    """Durable write-ahead order lineage and SideDeck-owned position registry."""

    def __init__(self, path: str, *, baseline_position_ids: Iterable[int],
                 baseline_order_ids: Iterable[int]) -> None:
        self._protected = frozenset(baseline_position_ids)
        self._protected_orders = frozenset(baseline_order_ids)
        self._db = sqlite3.connect(Path(path), isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.executescript(_LINEAGE_DDL)

    def close(self) -> None:
        self._db.close()

    def record_pending(self, *, reference_id: str, kind: str, intent_id: str, book_id: str,
                       instrument_id: int, units: Decimal | None, limit_rate: Decimal | None,
                       position_id: int | None) -> None:
        if position_id is not None and position_id in self._protected:
            raise EtoroDemoBookError("baseline positions are read-only and never closed by SideDeck")
        try:
            self._db.execute(
                "INSERT INTO etoro_demo_lineage_orders(reference_id,kind,intent_id,book_id,"
                "instrument_id,units,limit_rate,position_id,state,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?, 'PENDING_SUBMIT', ?)",
                (reference_id, kind, intent_id, book_id, instrument_id,
                 None if units is None else str(units),
                 None if limit_rate is None else str(limit_rate), position_id, _now()))
        except sqlite3.IntegrityError as exc:
            raise EtoroDemoOrderError("reference or intent already used; never reuse an x-request-id") from exc

    def order(self, reference_id: str) -> sqlite3.Row:
        row = self._db.execute("SELECT * FROM etoro_demo_lineage_orders WHERE reference_id=?",
                               (reference_id,)).fetchone()
        if row is None:
            raise EtoroDemoOrderError("unknown SideDeck reference")
        return row  # type: ignore[no-any-return]

    def orders(self) -> list[sqlite3.Row]:
        return list(self._db.execute("SELECT * FROM etoro_demo_lineage_orders ORDER BY rowid"))

    def set_state(self, reference_id: str, state: str, *, order_id: int | None = None,
                  filled_units: Decimal | None = None) -> None:
        row = self.order(reference_id)
        if order_id is not None:
            if order_id in self._protected_orders:
                raise EtoroDemoBookError("broker order belongs to a baseline position")
            if row["order_id"] is not None and row["order_id"] != order_id:
                raise EtoroDemoOrderError("broker order ID changed for a SideDeck reference")
        try:
            self._db.execute(
                "UPDATE etoro_demo_lineage_orders SET state=?, order_id=COALESCE(?, order_id), "
                "filled_units=COALESCE(?, filled_units), updated_at=? WHERE reference_id=?",
                (state, order_id, None if filled_units is None else str(filled_units), _now(),
                 reference_id))
        except sqlite3.IntegrityError as exc:
            raise EtoroDemoOrderError("broker order ID already linked to another reference") from exc

    def register_position(self, *, reference_id: str, order_id: int, book_id: str,
                          instrument_id: int, position_id: int, units: Decimal,
                          remaining: Decimal) -> None:
        if position_id in self._protected:
            raise EtoroDemoBookError("broker reported a baseline position for a SideDeck order")
        existing = self._db.execute("SELECT * FROM etoro_demo_owned_positions WHERE position_id=?",
                                    (position_id,)).fetchone()
        if existing is not None:
            if (existing["order_id"], existing["book_id"]) != (order_id, book_id):
                raise EtoroDemoBookError("position is already owned through a different order")
            return
        self._db.execute(
            "INSERT INTO etoro_demo_owned_positions VALUES (?,?,?,?,?,?,?, 'OPEN', ?)",
            (position_id, reference_id, order_id, book_id, instrument_id, str(units),
             str(remaining), _now()))

    def owned(self, position_id: int) -> sqlite3.Row | None:
        row = self._db.execute("SELECT * FROM etoro_demo_owned_positions WHERE position_id=?",
                               (position_id,)).fetchone()
        return row  # type: ignore[no-any-return]

    def owned_positions(self) -> list[sqlite3.Row]:
        return list(self._db.execute("SELECT * FROM etoro_demo_owned_positions ORDER BY position_id"))

    def reduce_position(self, position_id: int, closed: Decimal) -> None:
        row = self.owned(position_id)
        if row is None:
            raise EtoroDemoBookError("position has no SideDeck lineage")
        remaining = Decimal(row["remaining_units"]) - closed
        if remaining < 0:
            raise EtoroDemoOrderError("closed units exceed SideDeck-owned units")
        self._db.execute("UPDATE etoro_demo_owned_positions SET remaining_units=?, state=? "
                         "WHERE position_id=?",
                         (str(remaining), "CLOSED" if remaining == 0 else "OPEN", position_id))

    def attributions(self) -> tuple[OrderAttribution, ...]:
        rows = self._db.execute("SELECT order_id, book_id FROM etoro_demo_lineage_orders "
                                "WHERE kind='OPEN' AND order_id IS NOT NULL ORDER BY order_id")
        return tuple(OrderAttribution(r["order_id"], r["book_id"]) for r in rows)


class EtoroDemoDesk:
    def __init__(self, *, outbox: DurablePaperIntentStore, controls: ApprovalKillSwitch,
                 lineage: EtoroDemoLineage, transport: EtoroDemoTransport,
                 policy: DemoDeskPolicy, baseline: Iterable[BaselinePosition],
                 budget: DemoRateBudget, pilot_release: Any = None) -> None:
        self._pilot_release = None
        if getattr(transport, "offline_simulation", False) is not True:
            # The general release stays NO_GO. The only exception is one active, owner-signed
            # SD-048 pilot release whose intent matches this desk's policy exactly.
            from sidedeck.application.sd048_pilot_release import PilotRelease
            if not isinstance(pilot_release, PilotRelease):
                raise BrokerExecutionDisabled(
                    f"eToro Demo execution release is {ETORO_DEMO_EXECUTION_RELEASE}; only the "
                    "offline simulator or a signed pilot release may be used")
            pilot_release.require_active()
            intent = pilot_release.intent
            if (policy.allowed_instrument_ids != frozenset({intent.instrument_id})
                    or policy.max_order_notional_usd > intent.max_notional_usd
                    or policy.max_open_positions_per_book != 1):
                raise BrokerExecutionDisabled("desk policy does not match the signed pilot intent")
            self._pilot_release = pilot_release
        self._outbox, self._controls, self._lineage = outbox, controls, lineage
        self._transport, self._policy = transport, policy
        self._baseline = tuple(baseline)
        self._budget = budget

    # ---- transport boundary -------------------------------------------------
    def _send(self, method: str, path: str, *, reference_id: str,
              body: dict[str, Any] | None = None, query: dict[str, str] | None = None) -> Any:
        """Writes must pre-acquire budget before write-ahead; reads acquire here."""
        require_demo_route(method, path)
        if method == "GET":
            self._budget.acquire(bucket_for(method, path))
        return self._transport.send(method, path, reference_id=reference_id, body=body, query=query)

    def _halt(self, reason: str) -> None:
        self._controls.trip(DESK_OPERATOR, reason)

    def _require_live(self) -> None:
        if self._controls.is_halted():
            raise EtoroDemoOrderError("kill-switch is active; no eToro Demo writes")

    # ---- open ---------------------------------------------------------------
    def submit_open(self, *, intent_id: str, strategy: str, request: DemoOpenRequest) -> str:
        self._require_live()
        book = STRATEGY_BOOKS.get(strategy)
        if book is None:
            raise EtoroDemoBookError("not a SideDeck strategy with an eToro Demo book")
        if request.instrument_id not in self._policy.allowed_instrument_ids:
            raise EtoroDemoOrderError("instrument is not on the owner allowlist")
        if request.max_notional_usd > self._policy.max_order_notional_usd:
            raise EtoroDemoOrderError("order notional exceeds the owner cap")
        open_in_book = sum(1 for p in self._lineage.owned_positions()
                           if p["book_id"] == book and p["state"] == "OPEN")
        if open_in_book >= self._policy.max_open_positions_per_book:
            raise EtoroDemoOrderError("book already holds the maximum open positions")
        if not self._controls.is_approved(intent_id, open_scope(book, request)):
            raise EtoroDemoOrderError("no verified, unexpired approval for this exact order")
        if self._pilot_release is not None:
            self._pilot_release.require_active()
            signed = self._pilot_release.intent
            if (strategy, request.instrument_id, request.units, request.limit_rate) != (
                    signed.strategy, signed.instrument_id, signed.units, signed.limit_rate):
                raise EtoroDemoOrderError("open differs from the signed pilot intent")
        self._budget.acquire("write")
        self._outbox.enqueue(PaperIntent(
            intent_id, request.reference_id, "sidedeck", "etoro", "paper", "etoro-demo", book,
            f"etoro:{request.instrument_id}", "BUY", request.units, request.limit_rate))
        if self._outbox.get(intent_id)["state"] != "QUEUED":
            raise EtoroDemoOrderError("intent was already dispatched; recover by referenceId")
        self._outbox.claim(intent_id)
        self._lineage.record_pending(reference_id=request.reference_id, kind="OPEN",
                                     intent_id=intent_id, book_id=book,
                                     instrument_id=request.instrument_id, units=request.units,
                                     limit_rate=request.limit_rate, position_id=None)
        self._outbox.record_simulated_submission(intent_id)
        try:
            payload = self._send("POST", DEMO_OPEN_PATH, reference_id=request.reference_id,
                                 body=request.body())
        except Exception:  # any write failure after write-ahead: outcome unknown, never resubmit
            self._lineage.set_state(request.reference_id, "OUTCOME_UNKNOWN")
            self._halt("open order outcome unknown; recover by referenceId lookup")
            return "OUTCOME_UNKNOWN"
        try:
            acceptance = parse_open_acceptance(payload, reference_id=request.reference_id)
        except EtoroDemoOrderError:
            # A 200 we cannot read may still be an accepted order: never resubmit.
            self._lineage.set_state(request.reference_id, "OUTCOME_UNKNOWN")
            self._halt("open acceptance unreadable; recover by referenceId lookup")
            return "OUTCOME_UNKNOWN"
        self._lineage.set_state(request.reference_id, "ACCEPTED", order_id=acceptance.order_id)
        self._outbox.acknowledge(intent_id)
        return "ACCEPTED"

    def _open_request(self, row: sqlite3.Row) -> DemoOpenRequest:
        return DemoOpenRequest(row["reference_id"], row["instrument_id"], Decimal(row["units"]),
                               Decimal(row["limit_rate"]))

    def refresh_open(self, reference_id: str) -> DemoOrderOutcome | None:
        """Read-only lookup by referenceId; records verified fills and owned positions."""
        row = self._lineage.order(reference_id)
        if row["kind"] != "OPEN":
            raise EtoroDemoOrderError("not an open-order reference")
        intent_id = row["intent_id"]
        try:
            payload = self._send("GET", DEMO_ORDER_LOOKUP_PATH, reference_id=str(uuid.uuid4()),
                                 query={"referenceId": reference_id})
        except TransportNotFound:
            if row["order_id"] is not None:
                self._halt("accepted order missing from broker lookup")
                raise EtoroDemoOrderError("broker no longer reports an accepted order") from None
            # A 404 is inconclusive: eToro may still land the order. Stay halted; no rejection
            # is recorded and nothing is resubmitted until an operator reconciles /pnl.
            self._lineage.set_state(reference_id, "NOT_FOUND_INCONCLUSIVE")
            self._halt("order not found after submission; outcome inconclusive")
            return None
        try:
            outcome = parse_order_lookup(payload, request=self._open_request(row),
                                         order_id=row["order_id"])
            self._lineage.set_state(reference_id, outcome.status, order_id=outcome.order_id)
            for e in outcome.executions:
                self._lineage.register_position(
                    reference_id=reference_id, order_id=outcome.order_id, book_id=row["book_id"],
                    instrument_id=outcome.instrument_id, position_id=e.position_id,
                    units=e.units, remaining=e.remaining_units)
        except (EtoroDemoOrderError, EtoroDemoBookError):
            self._halt("order lookup failed lineage verification")
            raise
        if self._outbox.get(intent_id)["state"] == "SUBMITTED_SIMULATED":
            self._outbox.acknowledge(intent_id)
        delta = outcome.filled_units - Decimal(row["filled_units"])
        if delta < 0:
            self._halt("broker reports fewer filled units than previously recorded")
            raise EtoroDemoOrderError("filled units decreased")
        if delta > 0:
            self._outbox.record_fill(intent_id, delta)
            self._lineage.set_state(reference_id, outcome.status, filled_units=outcome.filled_units)
        if outcome.status_id in NO_FILL_TERMINAL:
            self._outbox.record_rejection(intent_id, outcome.status)
        return outcome

    def recover(self) -> dict[str, str]:
        """After restart: look up every unresolved open by referenceId. Never resubmits."""
        results = {}
        for row in self._lineage.orders():
            if row["kind"] == "OPEN" and row["state"] in {
                    "PENDING_SUBMIT", "OUTCOME_UNKNOWN", "ACCEPTED", "RECEIVED", "PLACED",
                    "PARTIALLY_FILLED", "WAITING_FOR_MARKET", "PENDING_TRIGGERED_RATE"}:
                outcome = self.refresh_open(row["reference_id"])
                results[row["reference_id"]] = ("NOT_FOUND_INCONCLUSIVE" if outcome is None
                                                  else outcome.status)
        return results

    # ---- close --------------------------------------------------------------
    def submit_close(self, *, intent_id: str, request: DemoCloseRequest,
                     snapshot: DemoPortfolioSnapshot, now: datetime) -> str:
        self._require_live()
        if any(b.position_id == request.position_id for b in self._baseline):
            raise EtoroDemoBookError("baseline positions are read-only and never closed by SideDeck")
        snapshot.require_fresh(now)
        pending = [r for r in self._lineage.orders() if r["kind"] == "CLOSE"
                   and r["position_id"] == request.position_id
                   and r["state"] not in CLOSE_SETTLED_STATES]
        if pending:
            raise EtoroDemoOrderError("a close for this position is already outstanding")
        owned = self._lineage.owned(request.position_id)
        if owned is None or owned["state"] != "OPEN":
            raise EtoroDemoBookError("position has no open SideDeck lineage")
        live = next((p for p in snapshot.positions if p.position_id == request.position_id), None)
        if live is None or live.order_id != owned["order_id"] \
                or live.instrument_id != owned["instrument_id"] \
                or request.instrument_id != owned["instrument_id"]:
            self._halt("close target does not match verified lineage in the live snapshot")
            raise EtoroDemoBookError("live position does not match SideDeck lineage")
        remaining = Decimal(owned["remaining_units"])
        if request.units_to_deduct is not None and request.units_to_deduct > remaining:
            raise EtoroDemoOrderError("close exceeds SideDeck-owned units")
        if not self._controls.is_approved(intent_id, close_scope(owned["book_id"], request)):
            raise EtoroDemoOrderError("no verified, unexpired approval for this exact close")
        self._budget.acquire("write")
        self._lineage.record_pending(reference_id=request.reference_id, kind="CLOSE",
                                     intent_id=intent_id, book_id=owned["book_id"],
                                     instrument_id=request.instrument_id,
                                     units=request.units_to_deduct or remaining,
                                     limit_rate=None, position_id=request.position_id)
        try:
            payload = self._send("POST", request.path, reference_id=request.reference_id,
                                 body=request.body())
        except Exception:  # any write failure after write-ahead: outcome unknown, never resubmit
            self._lineage.set_state(request.reference_id, "OUTCOME_UNKNOWN")
            self._halt("close order outcome unknown; operator /pnl reconciliation required")
            return "OUTCOME_UNKNOWN"
        try:
            acceptance = parse_close_acceptance(payload, request=request)
        except EtoroDemoOrderError:
            self._lineage.set_state(request.reference_id, "OUTCOME_UNKNOWN")
            self._halt("close acceptance unreadable; operator /pnl reconciliation required")
            return "OUTCOME_UNKNOWN"
        self._lineage.set_state(request.reference_id, "ACCEPTED", order_id=acceptance.order_id)
        return "ACCEPTED"

    def refresh_close(self, reference_id: str) -> str:
        row = self._lineage.order(reference_id)
        if row["kind"] != "CLOSE":
            raise EtoroDemoOrderError("not a close-order reference")
        if row["order_id"] is None:
            raise EtoroDemoOrderError("close outcome unknown; reconcile a fresh /pnl snapshot")
        acceptance = CloseAcceptance(row["order_id"], row["position_id"])
        payload = self._send("GET", DEMO_CLOSE_INFO_PATH.format(order_id=row["order_id"]),
                             reference_id=str(uuid.uuid4()))
        outcome = parse_close_info(payload, acceptance=acceptance)
        delta = outcome.closed_units - Decimal(row["filled_units"])
        if delta < 0 or outcome.closed_units > Decimal(row["units"]):
            self._halt("close fill inconsistent with the request")
            raise EtoroDemoOrderError("close fill inconsistent with the request")
        if delta > 0:
            self._lineage.reduce_position(row["position_id"], delta)
        self._lineage.set_state(reference_id, outcome.status, filled_units=outcome.closed_units)
        return outcome.status

    def recover_close_from_snapshot(self, reference_id: str, *,
                                    snapshot: DemoPortfolioSnapshot, now: datetime) -> str:
        """Resolve a close whose response was lost, using a fresh documented /pnl snapshot.

        ``orders:lookup`` for close orders is ``CLOSE_LOOKUP_RECOVERY=NOT_VERIFIED``, so the
        broker-reported position units decide. The kill-switch stays tripped; clearing it is
        a separate operator action.
        """
        row = self._lineage.order(reference_id)
        if row["kind"] != "CLOSE" or row["state"] != "OUTCOME_UNKNOWN":
            raise EtoroDemoOrderError("only a close with an unknown outcome can be recovered")
        snapshot.require_fresh(now)
        owned = self._lineage.owned(row["position_id"])
        if owned is None:
            raise EtoroDemoBookError("position has no SideDeck lineage")
        before = Decimal(owned["remaining_units"])
        live = next((p for p in snapshot.positions if p.position_id == row["position_id"]), None)
        if live is not None and (live.order_id != owned["order_id"] or live.units > before):
            self._halt("close recovery snapshot contradicts lineage")
            raise EtoroDemoBookError("snapshot contradicts SideDeck lineage")
        closed = before if live is None else before - live.units
        if closed > Decimal(row["units"]):
            self._halt("close recovery shows more units closed than requested")
            raise EtoroDemoOrderError("more units closed than the close requested")
        if closed > 0:
            self._lineage.reduce_position(row["position_id"], closed)
        state = ("RECONCILED_NOT_EXECUTED" if closed == 0 else
                 "RECONCILED_CLOSED_BY_SNAPSHOT" if live is None else
                 "RECONCILED_PARTIAL_BY_SNAPSHOT")
        self._lineage.set_state(reference_id, state, filled_units=closed)
        return state

    # ---- reconciliation -----------------------------------------------------
    def reconcile(self, snapshot: DemoPortfolioSnapshot, now: datetime) -> dict[str, Any]:
        report = reconcile_demo(snapshot, baseline=self._baseline,
                                attributions=self._lineage.attributions(), now=now)
        issues = list(report.discrepancies)
        live = {p.position_id: p for p in snapshot.positions}
        owned = {r["position_id"]: r for r in self._lineage.owned_positions()}
        for position_id, row in owned.items():
            current = live.get(position_id)
            if row["state"] == "OPEN" and current is None:
                issues.append(f"SideDeck position {position_id} is not open at the broker")
            elif row["state"] == "CLOSED" and current is not None:
                issues.append(f"SideDeck position {position_id} is closed locally but open at broker")
            elif current is not None and current.units != Decimal(row["remaining_units"]):
                issues.append(f"SideDeck position {position_id} units differ from lineage")
        sidedeck_orders = {a.order_id for a in self._lineage.attributions()}
        for position in snapshot.positions:
            if position.order_id in sidedeck_orders and position.position_id not in owned:
                issues.append(f"position {position.position_id} from a SideDeck order lacks "
                              "verified lookup lineage")
        if issues:
            self._halt("eToro Demo reconciliation discrepancy")
        return {
            "status": "DISCREPANCY" if issues else "MATCHED",
            "discrepancies": sorted(set(issues)),
            "books": {book: len(view.position_ids) for book, view in report.books.items()},
            "baseline_positions_protected": len(self._baseline),
            "kill_switch": "HALTED" if self._controls.is_halted() else "CLEAR",
            "etoro_demo_execution_release": ETORO_DEMO_EXECUTION_RELEASE,
            "etoro_real_execution": ETORO_REAL_EXECUTION,
            "broker_execution": "DISABLED",
        }


class OfflineEtoroDemoSimulator:
    """Deterministic, in-memory stand-in for the documented Demo endpoints.

    Results are ``offline-simulated`` and are never broker evidence. Honours the
    documented x-request-id idempotency (same reference -> same order).
    """

    offline_simulation = True

    def __init__(self, *, fill_price: Decimal, first_position_id: int = 880_001,
                 first_order_id: int = 770_001) -> None:
        self.fill_price = fill_price
        self.next_position_id = first_position_id
        self.next_order_id = first_order_id
        self.mode = "FILL"                    # FILL | PARTIAL | REJECT | PENDING
        self.close_mode = "FILL"              # FILL | PARTIAL | PENDING
        self.lose_next_response = False
        self.drop_next_request = False        # never reaches the broker (lookup -> 404)
        self.force_position_id: int | None = None
        self.baseline_rows: list[dict[str, Any]] = []   # served by the simulated /pnl GET
        self.calls: list[tuple[str, str]] = []
        self._orders: dict[str, dict[str, Any]] = {}
        self._close_orders: dict[int, dict[str, Any]] = {}

    def _new_order_id(self) -> int:
        self.next_order_id += 1
        return self.next_order_id - 1

    def send(self, method: str, path: str, *, reference_id: str,
             body: dict[str, Any] | None = None, query: dict[str, str] | None = None) -> Any:
        self.calls.append((method, path))
        if self.drop_next_request:
            self.drop_next_request = False
            raise TransportOutcomeUnknown("simulated connection reset before delivery")
        if method == "GET" and path == DEMO_PNL_PATH:
            return self.pnl_payload(self.baseline_rows)
        if method == "POST" and path == DEMO_OPEN_PATH:
            result = self._open(reference_id, body or {})
        elif method == "GET" and path == DEMO_ORDER_LOOKUP_PATH:
            order = self._orders.get((query or {}).get("referenceId", ""))
            if order is None:
                raise TransportNotFound("order not found")
            return order
        elif method == "POST" and "/market-close-orders/positions/" in path:
            result = self._close(int(path.rsplit("/", 1)[1]), body or {})
        elif method == "GET" and "/close-orders/" in path:
            info = self._close_orders.get(int(path.rsplit("/", 1)[1]))
            if info is None:
                raise TransportNotFound("close order not found")
            return info
        else:
            raise TransportNotFound("simulated route not found")
        if self.lose_next_response:
            self.lose_next_response = False
            raise TransportOutcomeUnknown("simulated timeout after delivery")
        return result

    def _open(self, reference_id: str, body: dict[str, Any]) -> dict[str, Any]:
        if reference_id in self._orders:      # documented x-request-id idempotency
            order = self._orders[reference_id]
            return {"token": str(uuid.uuid4()), "orderId": order["orderId"],
                    "referenceId": reference_id}
        order_id = self._new_order_id()
        units = Decimal(str(body["units"]))
        status, executions = (2 if self.mode == "PENDING" else 4), []
        if self.mode in ("FILL", "PARTIAL"):
            filled = units if self.mode == "FILL" else units / 2
            position_id = self.force_position_id or self.next_position_id
            self.next_position_id += 1
            executions = [{"positionId": position_id, "state": "open",
                           "remainingUnits": float(filled),
                           "openingData": {"orderId": order_id, "units": float(filled),
                                           "avgPrice": float(self.fill_price), "fees": 0}}]
            status = 3 if self.mode == "FILL" else 9
        order = {"orderId": order_id, "action": "open", "transaction": "buy",
                 "status": {"id": status, "name": "sim", "errorCode": 0 if status != 4 else 1},
                 "asset": {"instrumentId": body["instrumentId"], "leverage": 1, "side": "long"},
                 "positionExecutions": executions}
        self._orders[reference_id] = order
        return {"token": str(uuid.uuid4()), "orderId": order_id, "referenceId": reference_id}

    def _close(self, position_id: int, body: dict[str, Any]) -> dict[str, Any]:
        order_id = self._new_order_id()
        units = body.get("UnitsToDeduct")
        if units is None:
            opened = next(Decimal(str(e["remainingUnits"])) for o in self._orders.values()
                          for e in o["positionExecutions"] if e["positionId"] == position_id)
            already = sum((Decimal(str(p["units"])) for c in self._close_orders.values()
                           for p in c["positions"] if p["positionID"] == position_id), ZERO)
            units = float(opened - already)
        if self.close_mode == "PENDING":
            status, rows = 2, []
        elif self.close_mode == "PARTIAL":
            status, rows = 9, [{"positionID": position_id, "units": units / 2}]
        else:
            status, rows = 3, [{"positionID": position_id, "units": units}]
        self._close_orders[order_id] = {"orderID": order_id, "statusID": status, "positions": rows}
        return {"orderForClose": {"positionID": position_id, "instrumentID": body["InstrumentID"],
                                  "orderID": order_id, "unitsToDeduct": units, "statusID": 1}}

    def pnl_payload(self, baseline_rows: list[dict[str, Any]]) -> dict[str, Any]:
        """A synthetic /pnl body: the given baseline rows plus open simulated positions."""
        rows = list(baseline_rows)
        closed: dict[int, Decimal] = {}
        for close in self._close_orders.values():
            for p in close["positions"]:
                closed[p["positionID"]] = closed.get(p["positionID"], ZERO) + Decimal(str(p["units"]))
        for order in self._orders.values():
            for e in order["positionExecutions"]:
                remaining = Decimal(str(e["remainingUnits"])) - closed.get(e["positionId"], ZERO)
                if remaining > 0:
                    rows.append({"positionID": e["positionId"],
                                 "instrumentID": order["asset"]["instrumentId"],
                                 "orderID": order["orderId"], "isBuy": True,
                                 "units": float(remaining), "amount": 1, "leverage": 1,
                                 "openDateTime": "2026-10-21T14:30:00Z",
                                 "unrealizedPnL": {"pnL": 0}})
        return {"clientPortfolio": {"positions": rows, "credit": 0, "bonusCredit": 0,
                                    "accountCurrencyId": 1, "mirrors": [], "orders": [],
                                    "ordersForOpen": [], "ordersForClose": [],
                                    "ordersForCloseMultiple": [], "entryOrders": [],
                                    "exitOrders": [], "stockOrders": []}}


SYNTHETIC_BASELINE_ROWS = [
    {"positionID": n, "instrumentID": 1001, "orderID": 9000 + n, "isBuy": True, "units": 1,
     "amount": 100, "leverage": 1, "openDateTime": "2026-09-01T14:30:00Z",
     "unrealizedPnL": {"pnL": 0}} for n in (11, 12, 13, 14)]


def rehearse(workdir: str) -> dict[str, Any]:
    """Offline rehearsal on synthetic data: open, lost response, recovery, close, reconcile."""
    root = Path(workdir)
    now = datetime.now(timezone.utc)
    sim = OfflineEtoroDemoSimulator(fill_price=Decimal("100"))
    baseline = tuple(BaselinePosition.of(p) for p in parse_demo_portfolio(
        sim.pnl_payload(SYNTHETIC_BASELINE_ROWS), observed_at=now).positions)
    controls = ApprovalKillSwitch(str(root / "controls.sqlite3"),
                                  lambda key, digest, sig: sig == f"{key}:{digest}")
    lineage = EtoroDemoLineage(str(root / "lineage.sqlite3"),
                               baseline_position_ids=[b.position_id for b in baseline],
                               baseline_order_ids=[b.order_id for b in baseline if b.order_id])
    outbox = DurablePaperIntentStore(str(root / "outbox.sqlite3"))
    budget = DemoRateBudget(str(root / "budget.sqlite3"))
    desk = EtoroDemoDesk(outbox=outbox, controls=controls, lineage=lineage, transport=sim,
                         policy=DemoDeskPolicy(Decimal("500"), frozenset({1001}), 2),
                         baseline=baseline, budget=budget)
    expiry = now + timedelta(minutes=10)

    def approve(intent_id: str, scope: str) -> None:
        digest = intent_digest(intent_id, scope)
        controls.approve(f"approval-{intent_id}", intent_id, scope, "sidedeck-requester",
                         "rehearsal-approver", "rehearsal-key", f"rehearsal-key:{digest}", expiry)

    try:
        open_request = DemoOpenRequest(str(uuid.uuid4()), 1001, Decimal("2"), Decimal("101"))
        approve("open-1", open_scope("etoro-demo:tradingagents", open_request))
        sim.lose_next_response = True
        submitted = desk.submit_open(intent_id="open-1", strategy="tradingagents",
                                     request=open_request)
        recovered = desk.recover()
        controls.clear("rehearsal-operator", "lookup recovered the order")
        owned = lineage.owned_positions()[0]
        snapshot = parse_demo_portfolio(sim.pnl_payload(SYNTHETIC_BASELINE_ROWS), observed_at=now)
        baseline_close_refused = False
        try:
            desk.submit_close(intent_id="close-baseline", snapshot=snapshot, now=now,
                              request=DemoCloseRequest(str(uuid.uuid4()), 11, 1001))
        except EtoroDemoBookError:
            baseline_close_refused = True
        close_request = DemoCloseRequest(str(uuid.uuid4()), owned["position_id"], 1001)
        approve("close-1", close_scope("etoro-demo:tradingagents", close_request))
        desk.submit_close(intent_id="close-1", request=close_request, snapshot=snapshot, now=now)
        close_status = desk.refresh_close(close_request.reference_id)
        final = desk.reconcile(parse_demo_portfolio(sim.pnl_payload(SYNTHETIC_BASELINE_ROWS),
                                                    observed_at=now), now)
    finally:
        outbox.close()
        controls.close()
        lineage.close()
        budget.close()
    return {"evidence": "OFFLINE_SIMULATED_NOT_BROKER_EVIDENCE",
            "open_submit": submitted, "recovery": sorted(recovered.values()),
            "baseline_close_refused": baseline_close_refused, "close": close_status,
            "reconciliation": final, "authenticated_requests": 0, "orders_sent_to_etoro": 0}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline eToro Demo desk rehearsal (no network)")
    parser.add_argument("--rehearse", action="store_true", required=True)
    parser.parse_args(argv)
    with tempfile.TemporaryDirectory() as workdir:
        print(json.dumps(rehearse(workdir), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
