"""SD-046/SD-051 eToro Demo pilot runner, exercised OFFLINE against the simulator.

Plan (12 requests, 2 writes, no write retries, every response shape-checked):

1. ``preflight``: ``/pnl`` (baseline MATCHED, nothing pending, no SideDeck positions)
   -> Demo eligibility (open/close allowed, units-based, fractional if needed,
   notional >= eToro minimum) -> realtime rates (fresh <= 60 s). The limit is
   ``min(signed max, ask x 1.005)`` and is refused if the ask is above the signed
   max. Produces the exact open request for the owner's separate approval signature.
2. ``open_phase``: refuses a quote older than 5 minutes; one open; up to 3 lookups.
3. ``close_phase`` (separately approved): ``/pnl`` -> one full close -> up to 2
   close-outcome reads -> final ``/pnl``.

``COMPLETE`` only when the close is FILLED, the final snapshot is MATCHED and no
SideDeck position remains. Anything unconfirmed -> ``UNRESOLVED_OPERATOR_INTERVENTION_
REQUIRED``, kill-switch tripped, position kept OPEN, no further request.

Brokers are reached only through ``EtoroDemoDesk`` and ``PilotTransport``; the desk
accepts only the offline simulator or a matching, owner-signed SD-048 release.
"""
from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from sidedeck.application.sd033_approval_killswitch import ApprovalKillSwitch
from sidedeck.application.sd036_etoro_demo_desk import (
    EtoroDemoDesk, EtoroDemoLineage, EtoroDemoTransport, close_scope, open_scope,
)
from sidedeck.domain.etoro_demo import DemoPortfolioSnapshot, field_type_issues, parse_demo_portfolio
from sidedeck.domain.etoro_demo_books import STRATEGY_BOOKS, BaselinePosition, reconcile_demo
from sidedeck.domain.etoro_demo_orders import (
    DEMO_ELIGIBILITY_PATH, DEMO_OPEN_PATH, DEMO_ORDER_LOOKUP_PATH, DEMO_PNL_PATH,
    MARKET_DATA_RATES_PATH, NO_FILL_TERMINAL, DemoCloseRequest, DemoOpenRequest, Eligibility,
    FreshQuote,
    derive_limit, parse_eligibility, parse_fresh_quote, require_demo_route,
    response_shape_issues,
)

ROUTE_CAPS = {"pnl": 3, "eligibility": 1, "rates": 1, "open": 1, "lookup": 3, "close": 1,
              "close_info": 2}                                           # 12 total, 2 writes
MAX_NOTIONAL_USD = Decimal("50")
MAX_LIMIT_PREMIUM = Decimal("0.005")      # over the FRESH reference, enforced at preflight
MAX_PLANNING_HEADROOM = Decimal("0.05")   # signed max limit vs the signed planning reference
MAX_QUOTE_AGE_AT_OPEN = timedelta(minutes=5)
PILOT_OPERATOR = "sidedeck-etoro-demo-pilot"
UNRESOLVED = "UNRESOLVED_OPERATOR_INTERVENTION_REQUIRED"
_CLOSE_TERMINAL = {"FILLED", "REJECTED", "CANCELED", "EXPIRED", "CANCELED_PARTIALLY_FILLED",
                   "REJECTED_PARTIALLY_FILLED"}


class PilotError(RuntimeError):
    """A pilot control refused; recorded as a kill criterion."""


class PilotBudgetExhausted(PilotError):
    pass


class PilotShapeError(PilotError):
    pass


def route_for(method: str, path: str) -> tuple[str, str | None]:
    if method == "GET" and path == DEMO_PNL_PATH:
        return "pnl", None
    if method == "POST" and path == DEMO_ELIGIBILITY_PATH:
        return "eligibility", "eligibility"
    if method == "GET" and path == MARKET_DATA_RATES_PATH:
        return "rates", "rates"
    if method == "POST" and path == DEMO_OPEN_PATH:
        return "open", "open_acceptance"
    if method == "GET" and path == DEMO_ORDER_LOOKUP_PATH:
        return "lookup", "order_lookup"
    if method == "POST" and "/market-close-orders/positions/" in path:
        return "close", "close_acceptance"
    if method == "GET" and "/close-orders/" in path:
        return "close_info", "close_info"
    raise PilotError("route is outside the pilot plan")


class PilotBudget:
    """Persistent per-route request caps, reserved before each send."""

    def __init__(self, path: str) -> None:
        self._db = sqlite3.connect(Path(path), isolation_level=None)
        self._db.execute("CREATE TABLE IF NOT EXISTS sd046_pilot_budget "
                         "(route TEXT PRIMARY KEY, used INTEGER NOT NULL)")

    def close(self) -> None:
        self._db.close()

    def reserve(self, route: str) -> None:
        self._db.execute("BEGIN IMMEDIATE")
        try:
            row = self._db.execute("SELECT used FROM sd046_pilot_budget WHERE route=?",
                                   (route,)).fetchone()
            used = 0 if row is None else int(row[0])
            if used >= ROUTE_CAPS[route]:
                raise PilotBudgetExhausted(f"pilot {route} budget {ROUTE_CAPS[route]} exhausted")
            self._db.execute("INSERT INTO sd046_pilot_budget VALUES (?, 1) ON CONFLICT(route) "
                             "DO UPDATE SET used = used + 1", (route,))
            self._db.execute("COMMIT")
        except BaseException:
            if self._db.in_transaction:
                self._db.execute("ROLLBACK")
            raise

    def usage(self) -> dict[str, int]:
        rows = dict(self._db.execute("SELECT route, used FROM sd046_pilot_budget"))
        return {route: int(rows.get(route, 0)) for route in ROUTE_CAPS}


class PilotTransport:
    """Budget + shape-check wrapper. Inherits (never upgrades) the inner simulation flag."""

    def __init__(self, inner: EtoroDemoTransport, budget: PilotBudget) -> None:
        self.offline_simulation = getattr(inner, "offline_simulation", False) is True
        self._inner, self._budget = inner, budget

    def send(self, method: str, path: str, *, reference_id: str,
             body: dict[str, Any] | None = None, query: dict[str, str] | None = None) -> Any:
        require_demo_route(method, path)
        route, shape = route_for(method, path)
        self._budget.reserve(route)
        result = self._inner.send(method, path, reference_id=reference_id, body=body, query=query)
        issues = field_type_issues(result) if shape is None else response_shape_issues(shape, result)
        if issues:
            raise PilotShapeError(f"{route} response shape check failed ({len(issues)} issue(s))")
        return result


@dataclass(frozen=True)
class PilotScope:
    strategy: str
    instrument_id: int
    units: Decimal
    max_limit_rate: Decimal
    reference_price: Decimal

    def validate(self, baseline: tuple[BaselinePosition, ...]) -> None:
        if self.strategy not in STRATEGY_BOOKS:
            raise PilotError("pilot book must be a SideDeck strategy book")
        if any(b.instrument_id == self.instrument_id for b in baseline):
            raise PilotError("pilot instrument must not be held in the protected baseline")
        for value in (self.units, self.max_limit_rate, self.reference_price):
            if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
                raise PilotError("units, max limit and reference must be positive Decimals")
        if self.max_limit_rate > self.reference_price * (1 + MAX_PLANNING_HEADROOM):
            raise PilotError("signed max limit exceeds the 5 % planning headroom")
        if self.units * self.max_limit_rate > MAX_NOTIONAL_USD:
            raise PilotError("notional exceeds the USD 50 pilot cap")


class EtoroDemoPilot:
    def __init__(self, *, desk: EtoroDemoDesk, transport: PilotTransport, budget: PilotBudget,
                 controls: ApprovalKillSwitch, lineage: EtoroDemoLineage,
                 baseline: tuple[BaselinePosition, ...], scope: PilotScope,
                 release: Any = None) -> None:
        scope.validate(baseline)
        if release is not None and release.intent.scope() != scope:
            raise PilotError("pilot scope differs from the signed pilot release")
        self._desk, self._transport, self._budget = desk, transport, budget
        self._controls, self._lineage = controls, lineage
        self._baseline, self._scope = baseline, scope
        self._quote: FreshQuote | None = None
        self._eligibility: Eligibility | None = None
        self._open_request: DemoOpenRequest | None = None
        self._position_id: int | None = None

    # -- helpers ---------------------------------------------------------------
    def _snapshot(self) -> DemoPortfolioSnapshot:
        payload = self._transport.send("GET", DEMO_PNL_PATH, reference_id=str(uuid.uuid4()))
        return parse_demo_portfolio(payload, observed_at=datetime.now(timezone.utc))

    def _baseline_matched(self, snapshot: DemoPortfolioSnapshot) -> bool:
        report = reconcile_demo(snapshot, baseline=self._baseline,
                                attributions=self._lineage.attributions(),
                                now=datetime.now(timezone.utc))
        return report.status == "MATCHED"

    def _sidedeck_open(self) -> int:
        return sum(1 for p in self._lineage.owned_positions() if p["state"] == "OPEN")

    def _result(self, result: str, phase: str, **extra: Any) -> dict[str, Any]:
        usage = self._budget.usage()
        return {"result": result, "phase": phase, "requests_used": usage,
                "requests_total": sum(usage.values()),
                "writes": usage["open"] + usage["close"],
                "sidedeck_open_positions": self._sidedeck_open(),
                "kill_switch": "HALTED" if self._controls.is_halted() else "CLEAR",
                "execution_release": "NO_GO", **extra}

    def _unresolved(self, phase: str, reason: str) -> dict[str, Any]:
        if not self._controls.is_halted():
            self._controls.trip(PILOT_OPERATOR, f"pilot unresolved: {reason}")
        return self._result(UNRESOLVED, phase, reason=reason)

    # -- preflight -----------------------------------------------------------------
    def preflight(self) -> dict[str, Any]:
        """Read-only gates. On success, the exact open request awaits the owner's approval."""
        s = self._scope
        try:
            snapshot = self._snapshot()
            if (not self._baseline_matched(snapshot) or snapshot.pending_orders
                    or self._sidedeck_open()):
                return self._result("ABORTED_PREFLIGHT", "preflight",
                                    reason="baseline not MATCHED or positions/orders pending")
            eligibility = parse_eligibility(
                self._transport.send("POST", DEMO_ELIGIBILITY_PATH, reference_id=str(uuid.uuid4()),
                                     body={"instrumentIds": [s.instrument_id], "currency": "USD"}),
                instrument_id=s.instrument_id, units=s.units,
                notional_usd=s.units * s.max_limit_rate)
            now = datetime.now(timezone.utc)
            quote = parse_fresh_quote(
                self._transport.send("GET", MARKET_DATA_RATES_PATH, reference_id=str(uuid.uuid4()),
                                     query={"instrumentIds": str(s.instrument_id)}),
                instrument_id=s.instrument_id, now=now)
            limit = derive_limit(quote.ask, s.max_limit_rate, MAX_LIMIT_PREMIUM)
        except Exception as exc:  # no write has happened; abort cleanly
            return self._result("ABORTED_PREFLIGHT", "preflight",
                                reason=f"{type(exc).__name__}: {exc}")
        if s.units * limit < eligibility.min_position_usd:
            return self._result("ABORTED_PREFLIGHT", "preflight",
                                reason="order notional below eToro minimum at the derived limit")
        self._quote, self._eligibility = quote, eligibility
        self._open_request = DemoOpenRequest(str(uuid.uuid4()), s.instrument_id, s.units, limit)
        return self._result("READY_FOR_OPEN_APPROVAL", "preflight",
                            fractional=eligibility.fractional,
                            instrument_type_evidence=eligibility.instrument_type_evidence,
                            currency_evidence=eligibility.currency_evidence)

    def open_approval_scope(self) -> tuple[DemoOpenRequest, str]:
        """The exact open request and the SD-033 scope the owner must sign."""
        if self._open_request is None:
            raise PilotError("run a successful preflight first")
        return self._open_request, open_scope(STRATEGY_BOOKS[self._scope.strategy],
                                              self._open_request)

    # -- open phase --------------------------------------------------------------
    def open_phase(self, *, intent_id: str) -> dict[str, Any]:
        request, quote = self._open_request, self._quote
        if request is None or quote is None:
            raise PilotError("run a successful preflight first")
        if datetime.now(timezone.utc) - quote.observed_at > MAX_QUOTE_AGE_AT_OPEN:
            return self._result("ABORTED_PREFLIGHT", "open", reason="reference quote too old")
        try:
            self._desk.submit_open(intent_id=intent_id, strategy=self._scope.strategy,
                                   request=request, quote=quote,
                                   eligibility=self._eligibility)
            outcome = None
            for _ in range(ROUTE_CAPS["lookup"]):
                outcome = self._desk.refresh_open(request.reference_id)
                if outcome is None or outcome.terminal:
                    break
        except Exception as exc:  # any kill criterion after a write attempt
            return self._unresolved("open", type(exc).__name__)
        if outcome is None:
            return self._unresolved("open", "order not found after submission")
        if not outcome.terminal:
            return self._unresolved("open", "open outcome not terminal within budget")
        if outcome.status_id in NO_FILL_TERMINAL:
            try:
                clean = self._baseline_matched(self._snapshot()) and not self._sidedeck_open()
            except Exception as exc:
                return self._unresolved("open", type(exc).__name__)
            if not clean:
                return self._unresolved("open", "rejected open but final reconciliation not clean")
            return self._result("OPEN_REJECTED_CLEAN", "open", open_status=outcome.status)
        owned = [p for p in self._lineage.owned_positions()
                 if p["reference_id"] == request.reference_id and p["state"] == "OPEN"]
        if len(owned) != 1:
            return self._unresolved("open", "expected exactly one verified pilot position")
        self._position_id = int(owned[0]["position_id"])
        return self._result("OPEN_FILLED_AWAITING_CLOSE_APPROVAL", "open",
                            open_status=outcome.status)

    def close_request(self, reference_id: str) -> tuple[DemoCloseRequest, str]:
        """The exact close request and the approval scope the owner must sign."""
        if self._position_id is None:
            raise PilotError("no verified pilot position to close")
        request = DemoCloseRequest(reference_id, self._position_id, self._scope.instrument_id)
        return request, close_scope(STRATEGY_BOOKS[self._scope.strategy], request)

    # -- close phase -------------------------------------------------------------
    def close_phase(self, *, intent_id: str, request: DemoCloseRequest) -> dict[str, Any]:
        if self._position_id is None or request.position_id != self._position_id \
                or request.units_to_deduct is not None:
            raise PilotError("close must be a full close of the verified pilot position")
        try:
            snapshot = self._snapshot()
            state = self._desk.submit_close(intent_id=intent_id, request=request,
                                            snapshot=snapshot, now=datetime.now(timezone.utc))
        except Exception as exc:
            return self._unresolved("close", type(exc).__name__)
        if state == "OUTCOME_UNKNOWN":
            return self._unresolved("close", "close response lost")
        try:
            status = ""
            for _ in range(ROUTE_CAPS["close_info"]):
                status = self._desk.refresh_close(request.reference_id)
                if status in _CLOSE_TERMINAL:
                    break
            if status != "FILLED":
                return self._unresolved("close", f"close status {status or 'UNKNOWN'}")
            report = self._desk.reconcile(self._snapshot(), datetime.now(timezone.utc))
        except Exception as exc:
            return self._unresolved("close", type(exc).__name__)
        if report["status"] != "MATCHED" or self._sidedeck_open():
            return self._unresolved("close", "final reconciliation not MATCHED")
        return self._result("COMPLETE", "close", baseline_matched=len(self._baseline))
