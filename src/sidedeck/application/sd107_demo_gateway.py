"""SD-107 policy-bound offline gateway scaffold.

This module intentionally has no network transport.  The only executable gateway in this
branch is ``OfflineDemoGateway`` and it accepts only the deterministic local simulator.  The
eToro Demo deployment route remains ``NOT_RELEASED`` until the separate broker lifecycle,
off-machine anchoring, independent review and owner release are complete.
"""
from __future__ import annotations

import hashlib
import sqlite3
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Callable, Protocol

from sidedeck.application.sd063_autonomous_demo_policy import (
    AutonomousDemoPolicy, EntryProposal, ExitProposal, MAX_EXIT_FILL_DEVIATION,
    PolicyRefused, _UNKNOWN_OUTCOMES, OWNER_PRINCIPAL, protective_subject,
    check_grant_binding,
)
from sidedeck.application.sd068_track_scheduler import NEW_YORK
from sidedeck.application.sd064_unlock_grant import (
    GrantRefused, UnlockAuthority,
)
from sidedeck.application.sd074_trusted_inputs import (
    AuthenticatedRuntime, BrokerQuote, Envelope, SourceSigner,
)
from sidedeck.application.sd074_external_anchor import AnchorKeeper
from sidedeck.application.sd145_audit_journal import AuditJournal
from sidedeck.application.sd108_broker_adapters import (
    EtoroDemoReconciliationAdapter,
)
from sidedeck.domain.etoro_demo_orders import (
    CloseAcceptance, DemoCloseRequest, DemoOpenRequest, parse_close_acceptance,
)
from sidedeck.application.sd072_track_risk_limits import (
    TrackLimits, TrackRiskState, evaluate_track_risk,
)

BROKER_ROUTES = {"ETORO_DEMO": "NOT_RELEASED"}
SUBMISSION = "SIMULATED_LOCAL"


class GatewayRefused(PermissionError):
    """The policy or send-time checks refused the proposed simulation."""


class OpenSimulator(Protocol):
    """Narrow interface implemented only by the local deterministic simulator."""

    def open(self, request: DemoOpenRequest) -> dict[str, object]: ...

    def lookup(self, order_id: int) -> dict[str, object]: ...

    def close(self, request: DemoCloseRequest) -> tuple[dict[str, object],
                                                         dict[str, object], Decimal]: ...


class OfflineDemoSimulator:
    """Deterministic local fills; never performs I/O and never represents broker evidence."""

    def __init__(self, *, fill_price: Decimal, close_price: Decimal | None = None,
                 malformed_lookup: bool = False, storage_path: Path | None = None,
                 crash_after_open: bool = False, crash_after_close: bool = False) -> None:
        if not fill_price.is_finite() or fill_price <= 0:
            raise ValueError("simulator fill price must be positive and finite")
        self._fill_price = fill_price
        self._close_price = close_price if close_price is not None else fill_price
        if not self._close_price.is_finite() or self._close_price <= 0:
            raise ValueError("simulator close price must be positive and finite")
        self._malformed_lookup = malformed_lookup
        self._crash_after_open = crash_after_open
        self._crash_after_close = crash_after_close
        db_path = str(storage_path) if storage_path is not None else ":memory:"
        self._db = sqlite3.connect(db_path, isolation_level=None, timeout=10)
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS sim_orders (
                order_id INTEGER PRIMARY KEY AUTOINCREMENT,
                reference_id TEXT NOT NULL UNIQUE,
                action TEXT NOT NULL CHECK(action IN ('open', 'close')),
                instrument_id INTEGER NOT NULL,
                units TEXT NOT NULL,
                limit_rate TEXT NOT NULL,
                fill_price TEXT NOT NULL,
                position_id INTEGER
            );
            CREATE TABLE IF NOT EXISTS sim_positions (
                position_id INTEGER PRIMARY KEY,
                open_order_id INTEGER NOT NULL UNIQUE REFERENCES sim_orders(order_id),
                instrument_id INTEGER NOT NULL,
                units TEXT NOT NULL,
                closed INTEGER NOT NULL DEFAULT 0 CHECK(closed IN (0, 1))
            );
        """)

    def close_store(self) -> None:
        self._db.close()

    @property
    def submitted_orders(self) -> int:
        return int(self._db.execute("SELECT COUNT(*) FROM sim_orders WHERE action='open'").fetchone()[0])

    def open(self, request: DemoOpenRequest) -> dict[str, object]:
        if request.max_notional_usd <= 0 or request.limit_rate < self._fill_price:
            raise GatewayRefused("simulated IOC is not marketable within its limit")
        self._db.execute("BEGIN IMMEDIATE")
        try:
            row = self._db.execute(
                "SELECT order_id, instrument_id, units, limit_rate FROM sim_orders "
                "WHERE reference_id=? AND action='open'",
                (request.reference_id,),
            ).fetchone()
            if row is not None:
                if (row[1], Decimal(row[2]), Decimal(row[3])) != (
                    request.instrument_id, request.units, request.limit_rate
                ):
                    raise GatewayRefused("simulated idempotency reference reused with different order")
                order_id = int(row[0])
            else:
                cursor = self._db.execute(
                    "INSERT INTO sim_orders "
                    "(reference_id, action, instrument_id, units, limit_rate, fill_price) "
                    "VALUES (?, 'open', ?, ?, ?, ?)",
                    (request.reference_id, request.instrument_id, str(request.units),
                     str(request.limit_rate), str(self._fill_price)),
                )
                if cursor.lastrowid is None:
                    raise GatewayRefused("simulated open did not receive a durable order id")
                order_id = int(cursor.lastrowid)

            # The accepted order and its simulated position must be committed
            # atomically. A later order lookup is read-only, including after a
            # process restart; lookup may not manufacture or reopen a position.
            position_id = order_id + 100_000
            self._db.execute(
                "INSERT OR IGNORE INTO sim_positions "
                "(position_id, open_order_id, instrument_id, units) VALUES (?, ?, ?, ?)",
                (position_id, order_id, request.instrument_id, str(request.units)),
            )
            stored = self._db.execute(
                "SELECT open_order_id, instrument_id, units FROM sim_positions "
                "WHERE position_id=?", (position_id,),
            ).fetchone()
            if stored != (order_id, request.instrument_id, str(request.units)):
                raise GatewayRefused("simulated position lineage conflicts with durable order")
            self._db.execute("COMMIT")
        except BaseException:
            if self._db.in_transaction:
                self._db.execute("ROLLBACK")
            raise
        if self._crash_after_open:
            self._crash_after_open = False
            raise GatewayRefused("simulated process interruption after durable acceptance")
        return {"orderId": order_id, "referenceId": request.reference_id}

    def lookup(self, order_id: int) -> dict[str, object]:
        order = self._db.execute(
            "SELECT reference_id, instrument_id, units, limit_rate, fill_price "
            "FROM sim_orders WHERE order_id=? AND action='open'",
            (order_id,),
        ).fetchone()
        if order is None:
            raise GatewayRefused("simulated order does not exist")
        if self._malformed_lookup:
            return {"orderId": order_id, "status": "unexpected"}
        request = DemoOpenRequest(
            str(order[0]), int(order[1]), Decimal(order[2]), Decimal(order[3]),
        )
        position_id = order_id + 100_000
        position = self._db.execute(
            "SELECT open_order_id, instrument_id, units, closed FROM sim_positions "
            "WHERE position_id=?", (position_id,),
        ).fetchone()
        if position is None or position[:3] != (
            order_id, request.instrument_id, str(request.units)
        ):
            raise GatewayRefused("durable simulated position lineage is missing or mismatched")
        closed = bool(position[3])
        return {
            "orderId": order_id, "action": "open", "transaction": "buy",
            "status": {"id": 3, "errorCode": 0},
            "asset": {"instrumentId": request.instrument_id, "leverage": 1,
                      "side": "long"},
            "positionExecutions": [{
                "positionId": position_id, "state": "closed" if closed else "open",
                "remainingUnits": 0.0 if closed else float(request.units),
                "openingData": {"orderId": order_id, "units": float(request.units),
                                "avgPrice": float(Decimal(order[4])), "fees": 0.0},
            }],
        }

    def close(self, request: DemoCloseRequest) -> tuple[dict[str, object],
                                                          dict[str, object], Decimal]:
        self._db.execute("BEGIN IMMEDIATE")
        try:
            prior = self._db.execute("SELECT order_id, instrument_id, units, fill_price, position_id "
                                     "FROM sim_orders WHERE reference_id=? AND action='close'",
                                     (request.reference_id,)).fetchone()
            if prior is not None:
                if (int(prior[1]), Decimal(prior[2]), int(prior[4])) != (
                        request.instrument_id,
                        request.units_to_deduct if request.units_to_deduct is not None
                        else Decimal(prior[2]), request.position_id):
                    raise GatewayRefused("simulated close reference reused with different order")
                order_id, fill_price = int(prior[0]), Decimal(prior[3])
                units = Decimal(prior[2])
            else:
                position = self._db.execute("SELECT instrument_id, units, closed FROM sim_positions "
                                             "WHERE position_id=?", (request.position_id,)).fetchone()
                if position is None or position[0] != request.instrument_id or position[2]:
                    raise GatewayRefused("simulator position is missing, closed or mismatched")
                remaining = Decimal(position[1])
                units = request.units_to_deduct if request.units_to_deduct is not None else remaining
                if units != remaining:
                    raise GatewayRefused("simulator supports only full reduce-only closes")
                cursor = self._db.execute("INSERT INTO sim_orders "
                    "(reference_id, action, instrument_id, units, limit_rate, fill_price, position_id) "
                    "VALUES (?, 'close', ?, ?, '0', ?, ?)",
                    (request.reference_id, request.instrument_id, str(units),
                     str(self._close_price), request.position_id))
                if cursor.lastrowid is None:
                    raise GatewayRefused("simulated close did not receive a durable order id")
                order_id, fill_price = cursor.lastrowid, self._close_price
                self._db.execute("UPDATE sim_positions SET closed=1 WHERE position_id=?",
                                 (request.position_id,))
            self._db.execute("COMMIT")
        except BaseException:
            if self._db.in_transaction:
                self._db.execute("ROLLBACK")
            raise
        if self._crash_after_close:
            self._crash_after_close = False
            raise GatewayRefused("simulated process interruption after durable close")
        acceptance: dict[str, object] = {"orderForClose": {
            "positionID": request.position_id, "instrumentID": request.instrument_id,
            "orderID": order_id}}
        close_info: dict[str, object] = {"orderID": order_id, "statusID": 3,
                                        "positions": [{"positionID": request.position_id,
                                                       "units": float(units)}]}
        return acceptance, close_info, fill_price

    def lookup_reference(self, reference_id: str) -> dict[str, object]:
        row = self._db.execute("SELECT order_id FROM sim_orders WHERE reference_id=? AND action='open'",
                               (reference_id,)).fetchone()
        if row is None:
            raise GatewayRefused("no durable simulated acceptance exists for this reference")
        return self.lookup(int(row[0]))

    def order_id_for_reference(self, reference_id: str) -> int:
        row = self._db.execute("SELECT order_id FROM sim_orders WHERE reference_id=? AND action='open'",
                               (reference_id,)).fetchone()
        if row is None:
            raise GatewayRefused("no durable simulated acceptance exists for this reference")
        return int(row[0])

    def recover_close(self, request: DemoCloseRequest) -> tuple[dict[str, object],
                                                                dict[str, object], Decimal]:
        row = self._db.execute("SELECT order_id, instrument_id, units, fill_price, position_id "
                               "FROM sim_orders WHERE reference_id=? AND action='close'",
                               (request.reference_id,)).fetchone()
        if row is None or (int(row[1]), int(row[4])) != (request.instrument_id, request.position_id):
            raise GatewayRefused("no matching durable simulated close exists")
        order_id, units, price = int(row[0]), Decimal(row[2]), Decimal(row[3])
        if request.units_to_deduct is not None and request.units_to_deduct != units:
            raise GatewayRefused("recovery close quantity differs from durable order")
        acceptance: dict[str, object] = {"orderForClose": {
            "positionID": request.position_id, "instrumentID": request.instrument_id,
            "orderID": order_id}}
        info: dict[str, object] = {"orderID": order_id, "statusID": 3,
                                   "positions": [{"positionID": request.position_id,
                                                  "units": float(units)}]}
        return acceptance, info, price


class OfflineDemoGateway:
    """Require SD-064 grants, SD-063 proposals and SD-074 seals before local simulation.

    This class is deliberately unable to select an HTTP client.  Deployable broker transport
    must be a separately reviewed implementation; changing ``BROKER_ROUTES`` here cannot
    unlock the SD-103 production route.
    """

    def __init__(self, *, policy: AutonomousDemoPolicy,
                 runtime: AuthenticatedRuntime, authority: UnlockAuthority,
                 grant_document: dict[str, object], grant_signature: str,
                 simulator: OfflineDemoSimulator, reconciliation_signer: SourceSigner,
                 anchor_keeper: AnchorKeeper,
                 audit_journal: AuditJournal | None = None,
                 protective_grant: tuple[dict[str, object], str] | None = None,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        if type(simulator) is not OfflineDemoSimulator:
            raise GatewayRefused("only the offline simulator is accepted by this gateway")
        if audit_journal is None:
            raise GatewayRefused("externally anchored audit journal is required")
        if runtime.ledger.policy_digest != policy.digest():
            raise GatewayRefused("runtime ledger is bound to a different policy")
        try:
            authority.bind_audit_journal(audit_journal)
        except GrantRefused as exc:
            raise GatewayRefused("unlock authority audit journal binding failed") from exc
        self._policy, self._runtime, self._authority = policy, runtime, authority
        self._document, self._signature = grant_document, grant_signature
        self._protective_grant = protective_grant
        self._anchor_keeper = anchor_keeper
        self._audit_journal = audit_journal
        self._simulator, self._clock = simulator, clock
        self._adapter = EtoroDemoReconciliationAdapter(reconciliation_signer)

    def _audit(self, event_type: str, reference_id: str, *, payload: dict[str, object]) -> None:
        try:
            self._audit_journal.append(event_type, entity_id=reference_id,
                                       payload=payload, at=self._clock())
        except Exception as exc:
            try:
                self._runtime.ledger.trip_kill_switch(
                    "AUDIT_ANCHOR_UNAVAILABLE", self._clock())
            except Exception:
                # The audit failure remains the primary refusal; no send follows it.
                pass
            raise GatewayRefused("external audit evidence unavailable; operation refused") from exc

    def _publish_before_send(self, now: datetime) -> None:
        """Publish every policy-ledger tail before a simulated broker request."""
        try:
            self._anchor_keeper.publish(self._runtime.ledger, now)
            self._anchor_keeper.require_published(self._runtime.ledger)
        except PolicyRefused as exc:
            raise GatewayRefused("policy ledger is not externally anchored") from exc

    def _authorize(self, *, write: bool, reference_id: str,
                   protective: bool = False) -> None:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise GatewayRefused("gateway clock must be timezone-aware")
        document, signature, subject = self._document, self._signature, self._policy.digest()
        if protective:
            if self._protective_grant is None:
                raise GatewayRefused("protective-exit grant is not configured")
            document, signature = self._protective_grant
            subject = protective_subject(self._policy)
        self._publish_before_send(now)
        try:
            grant = self._authority.authorize_request(
                document=document, signature=signature,
                subject_digest=subject, write=write,
                reference_id=reference_id, now=now,
            )
            if protective:
                if (grant.kind != "autonomous_policy" or grant.issued_by != OWNER_PRINCIPAL
                        or grant.broker != "etoro-demo"
                        or grant.not_before < self._policy.not_before):
                    raise PolicyRefused("protective grant is outside its reduce-only scope")
            else:
                check_grant_binding(self._policy, grant, now.astimezone(timezone.utc))
        except (GrantRefused, PolicyRefused) as exc:
            raise GatewayRefused("signed grant refused") from exc
        self._audit("POLICY", self._policy.policy_id,
                    payload={"policy_digest": self._policy.digest(),
                             "broker": self._policy.broker})
        self._audit("GRANT", grant.grant_id,
                    payload={"grant_digest": grant.digest(),
                             "subject_digest": grant.subject_digest,
                             "expires_at": grant.expires_at.isoformat()})

    def _validate_entry_at_send(self, proposal: EntryProposal, now: datetime,
                                quotes: dict[str, BrokerQuote]) -> None:
        if proposal.submission != "OFFLINE_PROPOSAL_NOT_SUBMITTED":
            raise GatewayRefused("proposal submission state is not eligible")
        if proposal.policy_digest != self._policy.digest():
            raise GatewayRefused("proposal belongs to a different policy")
        if not self._policy.active(now):
            raise GatewayRefused("policy is outside its signed window")
        if (now - proposal.proposed_at).total_seconds() > self._policy.max_quote_age_seconds:
            raise GatewayRefused("proposal quote freshness expired before send")
        if self._runtime.ledger.kill_switch_engaged():
            raise GatewayRefused("policy kill-switch is engaged")
        state = self._runtime.ledger.state()
        entry = state.entries.get(proposal.reference_id)
        if entry is None or entry.outcome is not None:
            raise GatewayRefused("proposal is absent, resolved or already submitted")
        if (entry.track, entry.canonical_id, entry.instrument, entry.units, entry.limit) != (
                proposal.track, proposal.canonical_id, proposal.etoro_instrument_id,
                proposal.units, proposal.limit_price):
            raise GatewayRefused("proposal does not match the durable policy ledger")
        current = quotes.get(proposal.canonical_id)
        if current is None or current.ask > proposal.limit_price:
            raise GatewayRefused("fresh sealed ask is absent or above the proposal limit")
        if any(item.quote_time > now or
               (now - item.quote_time).total_seconds() > self._policy.max_quote_age_seconds
               for item in quotes.values()):
            raise GatewayRefused("send-time quote or risk mark is stale/future-dated under policy")
        budget = self._policy.budget(proposal.track)
        if budget is None or entry.units * entry.limit > budget.max_position_notional:
            raise GatewayRefused("per-position notional cap exceeded")
        day = now.astimezone(NEW_YORK).date()
        order_count = self._runtime.ledger.count_events(
            ("ENTRY_PROPOSED", "EXIT_PROPOSED"), proposal.track, day)
        if order_count > budget.max_orders_per_day:
            raise GatewayRefused("daily order cap exceeded at send time")
        exposure = sum((p.units * p.avg_price
                        for p in self._runtime.ledger.open_positions()), Decimal("0"))
        exposure += sum((p.units * p.limit for p in state.entries.values()
                         if p.outcome is None or p.outcome in _UNKNOWN_OUTCOMES), Decimal("0"))
        total_capital = sum((b.virtual_capital for b in self._policy.tracks), Decimal("0"))
        if exposure > total_capital or exposure > Decimal("1000"):
            raise GatewayRefused("aggregate exposure cap exceeded at send time")
        marks = {canonical: quote.bid for canonical, quote in quotes.items()}
        runtime = self._runtime.runtime
        equity = runtime._equity(state, proposal.track, budget.virtual_capital, marks)
        if equity is None:
            raise GatewayRefused("fresh marks for every open position are required at send time")
        prior_peak = max([budget.virtual_capital,
                          *(value for _, value in state.marks.get(proposal.track, []))])
        start = next((value for mark_day, value in state.marks.get(proposal.track, [])
                      if mark_day == day.isoformat()), None)
        if start is None or equity <= budget.virtual_capital * (1 - budget.max_loss_pct):
            raise GatewayRefused("daily or cumulative loss gate cannot be verified at send time")
        risk = evaluate_track_risk(
            TrackRiskState(proposal.track, equity, max(prior_peak, equity), start, order_count),
            TrackLimits(proposal.track, budget.max_drawdown_pct, budget.max_daily_loss_pct,
                        budget.max_orders_per_day),
        )
        if not risk.entries_allowed:
            raise GatewayRefused("send-time risk gate refused the entry")

    def submit_entry(self, proposal: EntryProposal, *, quote: Envelope,
                     marks: tuple[Envelope, ...] = ()) -> Envelope:
        """Simulate one guarded open and reconcile it through the sealed SD-074 path."""
        now = self._clock()
        try:
            verified_quotes = [self._runtime.verified_quote(envelope)
                               for envelope in (quote, *marks)]
        except Exception as exc:
            raise GatewayRefused("send-time quote verification failed") from exc
        if len({item.canonical_id for item in verified_quotes}) != len(verified_quotes):
            raise GatewayRefused("duplicate send-time quote for an instrument")
        self._validate_entry_at_send(
            proposal, now, {item.canonical_id: item for item in verified_quotes})
        self._audit("ORDER_RESERVATION", proposal.reference_id,
                    payload={"action": "OPEN", "policy_digest": self._policy.digest(),
                             "units": str(proposal.units),
                             "instrument_id": proposal.etoro_instrument_id})
        request_id = str(uuid.UUID(hex=proposal.reference_id))
        request = DemoOpenRequest(request_id, proposal.etoro_instrument_id, proposal.units,
                                  proposal.limit_price)
        self._authorize(write=True, reference_id=proposal.reference_id)
        try:
            self._audit("SEND", proposal.reference_id,
                        payload={"action": "OPEN", "policy_digest": self._policy.digest()})
            accepted = self._simulator.open(request)
            try:
                acceptance = self._adapter.parse_open_acceptance(accepted, request=request)
            except Exception as exc:
                self._runtime.ledger.trip_kill_switch("SIMULATED_OPEN_AMBIGUOUS", now)
                raise GatewayRefused("simulated open acceptance is malformed") from exc
            self._authorize(write=False, reference_id=f"lookup:{proposal.reference_id}")
            raw = self._simulator.lookup(acceptance.order_id)
            envelope = self._adapter.seal_open_lookup_or_unresolved(
                raw, request=request, observed_at=self._clock(),
                accepted_order_id=acceptance.order_id)
            self._runtime.resolve(envelope)
            self._audit("RECONCILIATION", proposal.reference_id,
                        payload={"action": "OPEN", "outcome": str(envelope.payload.get("outcome")),
                                 "evidence_sha256": hashlib.sha256(envelope.canonical()).hexdigest()})
            self._publish_before_send(self._clock())
            return envelope
        except Exception:
            # No replay/retry: any uncertain post-send result halts this policy.
            if not self._runtime.ledger.kill_switch_engaged():
                self._runtime.ledger.trip_kill_switch("SIMULATED_OUTCOME_UNRESOLVED", now)
            self._publish_before_send(self._clock())
            raise

    def recover_entry(self, proposal: EntryProposal) -> Envelope:
        """Reconcile an already proposed entry after restart; this method never sends an open."""
        state = self._runtime.ledger.state()
        entry = state.entries.get(proposal.reference_id)
        if (entry is None or proposal.policy_digest != self._policy.digest()
                or (entry.track, entry.canonical_id, entry.instrument, entry.units, entry.limit)
                != (proposal.track, proposal.canonical_id, proposal.etoro_instrument_id,
                    proposal.units, proposal.limit_price)
                or (entry.outcome is not None and entry.outcome not in _UNKNOWN_OUTCOMES)):
            raise GatewayRefused("entry is not an unresolved matching durable proposal")
        request = DemoOpenRequest(str(uuid.UUID(hex=proposal.reference_id)),
                                  proposal.etoro_instrument_id, proposal.units,
                                  proposal.limit_price)
        self._publish_before_send(self._clock())
        self._authorize(write=False, reference_id=f"recovery:{proposal.reference_id}")
        raw = self._simulator.lookup_reference(request.reference_id)
        envelope = self._adapter.seal_open_lookup_or_unresolved(
            raw, request=request, observed_at=self._clock(),
            accepted_order_id=self._simulator.order_id_for_reference(request.reference_id))
        outcome = envelope.payload.get("outcome")
        if entry.outcome in _UNKNOWN_OUTCOMES:
            if outcome != "UNRESOLVED":
                self._runtime.reconcile_unknown(envelope)
        else:
            self._runtime.resolve(envelope)
        self._audit("RECONCILIATION", proposal.reference_id,
                    payload={"action": "OPEN_RECOVERY", "outcome": str(outcome),
                             "evidence_sha256": hashlib.sha256(
                                 envelope.canonical()).hexdigest()})
        self._publish_before_send(self._clock())
        return envelope

    def validate_exit_at_send(self, proposal: ExitProposal, *, quote: Envelope
                              ) -> tuple[DemoCloseRequest, bool]:
        """Shared send-time validation for offline simulation and SD-138 fake transport."""
        now = self._clock()
        try:
            fresh = self._runtime.verified_quote(quote)
        except Exception as exc:
            raise GatewayRefused("exit quote verification failed") from exc
        protective = proposal.authority == "protective"
        if proposal.authority not in ("policy", "protective"):
            raise GatewayRefused("exit authority is unsupported")
        if (proposal.submission != "OFFLINE_PROPOSAL_NOT_SUBMITTED"
                or proposal.policy_digest != self._policy.digest()
                or (protective and self._policy.active(now))
                or (not protective and not self._policy.active(now))):
            raise GatewayRefused("exit proposal is outside its policy scope")
        if fresh.canonical_id != proposal.canonical_id or fresh.bid <= 0:
            raise GatewayRefused("fresh sealed bid does not match the exit instrument")
        if (fresh.quote_time > now or
                (now - fresh.quote_time).total_seconds() > self._policy.max_quote_age_seconds):
            raise GatewayRefused("send-time bid is stale or future-dated under policy")
        state = self._runtime.ledger.state()
        exit_row = state.exits.get(proposal.reference_id)
        entry = state.entries.get(proposal.entry_reference)
        if exit_row is None or exit_row.outcome is not None or entry is None:
            raise GatewayRefused("exit proposal is absent or already resolved")
        positions = {p.entry_reference: p for p in self._runtime.ledger.open_positions()}
        position = positions.get(proposal.entry_reference)
        if position is None or not position.broker_position_id or \
                str(position.broker_position_id) != str(proposal.broker_position_id):
            raise GatewayRefused("exit lacks verified SideDeck position lineage")
        if not position.broker_position_id.isdecimal():
            raise GatewayRefused("broker position id is not a numeric eToro position id")
        if (proposal.policy_digest != self._policy.digest()
                or (exit_row.entry, exit_row.units) !=
                (proposal.entry_reference, proposal.units)
                or (entry.track, entry.canonical_id, entry.instrument) !=
                (proposal.track, proposal.canonical_id, proposal.etoro_instrument_id)):
            raise GatewayRefused("exit proposal does not match the durable ledger")
        if abs(fresh.bid - exit_row.bid) > exit_row.bid * MAX_EXIT_FILL_DEVIATION:
            raise GatewayRefused("fresh bid differs materially from the planned close")
        if proposal.units != position.units or proposal.etoro_instrument_id in \
                self._policy.protected_instrument_ids:
            raise GatewayRefused("only a full reduce-only close of an owned position is allowed")
        if (now - proposal.proposed_at).total_seconds() > self._policy.max_quote_age_seconds:
            raise GatewayRefused("exit quote freshness expired before send")
        if entry.instrument != proposal.etoro_instrument_id \
                or entry.canonical_id != proposal.canonical_id:
            raise GatewayRefused("exit instrument does not match the position lineage")
        budget = self._policy.budget(proposal.track)
        if budget is None:
            raise GatewayRefused("exit track is outside the policy")
        day = now.astimezone(NEW_YORK).date()
        order_count = self._runtime.ledger.count_events(
            ("ENTRY_PROPOSED", "EXIT_PROPOSED"), proposal.track, day)
        if order_count > budget.max_orders_per_day:
            raise GatewayRefused("daily order cap exceeded at close send time")

        request = DemoCloseRequest(str(uuid.UUID(hex=proposal.reference_id)),
                                   int(position.broker_position_id),
                                   proposal.etoro_instrument_id, None)
        return request, protective

    def submit_exit(self, proposal: ExitProposal, *, quote: Envelope) -> Envelope:
        """Simulate a lineage-verified full close."""
        now = self._clock()
        request, protective = self.validate_exit_at_send(proposal, quote=quote)
        self._authorize(write=True, reference_id=proposal.reference_id, protective=protective)
        try:
            self._audit("ORDER_RESERVATION", proposal.reference_id,
                        payload={"action": "CLOSE", "policy_digest": self._policy.digest(),
                                 "units": str(proposal.units),
                                 "instrument_id": proposal.etoro_instrument_id})
            self._audit("SEND", proposal.reference_id,
                        payload={"action": "CLOSE", "policy_digest": self._policy.digest()})
            accepted_payload, close_payload, fill_price = self._simulator.close(request)
            try:
                acceptance: CloseAcceptance = parse_close_acceptance(
                    accepted_payload, request=request)
            except Exception as exc:
                self._runtime.ledger.trip_kill_switch("SIMULATED_CLOSE_AMBIGUOUS", now)
                raise GatewayRefused("simulated close acceptance is malformed") from exc
            self._authorize(write=False, reference_id=f"close-lookup:{proposal.reference_id}",
                             protective=protective)
            envelope = self._adapter.seal_simulated_close(
                close_payload, request=request, acceptance=acceptance,
                observed_at=self._clock(), fill_price=fill_price)
            self._runtime.resolve(envelope)
            self._audit("RECONCILIATION", proposal.reference_id,
                        payload={"action": "CLOSE", "outcome": str(envelope.payload.get("outcome")),
                                 "evidence_sha256": hashlib.sha256(envelope.canonical()).hexdigest()})
            self._publish_before_send(self._clock())
            return envelope
        except Exception:
            if not self._runtime.ledger.kill_switch_engaged():
                self._runtime.ledger.trip_kill_switch("SIMULATED_CLOSE_UNRESOLVED", now)
            self._publish_before_send(self._clock())
            raise

    def recover_exit(self, proposal: ExitProposal) -> Envelope:
        """Resolve a durable close after restart without submitting another close order."""
        state = self._runtime.ledger.state()
        row = state.exits.get(proposal.reference_id)
        entry = state.entries.get(proposal.entry_reference)
        position = next((p for p in self._runtime.ledger.open_positions()
                         if p.entry_reference == proposal.entry_reference), None)
        if (row is None or row.outcome is not None and row.outcome not in _UNKNOWN_OUTCOMES
                or entry is None or position is None or not position.broker_position_id
                or str(position.broker_position_id) != str(proposal.broker_position_id)
                or proposal.policy_digest != self._policy.digest()
                or (row.entry, row.units) != (proposal.entry_reference, proposal.units)):
            raise GatewayRefused("close is not an unresolved matching owned position")
        request = DemoCloseRequest(str(uuid.UUID(hex=proposal.reference_id)),
                                   int(position.broker_position_id), proposal.etoro_instrument_id,
                                   proposal.units)
        self._publish_before_send(self._clock())
        protective = proposal.authority == "protective"
        self._authorize(write=False, reference_id=f"close-recovery:{proposal.reference_id}",
                        protective=protective)
        accepted, close_info, fill_price = self._simulator.recover_close(request)
        acceptance = self._adapter.parse_close_acceptance(accepted, request=request)
        envelope = self._adapter.seal_simulated_close(
            close_info, request=request, acceptance=acceptance,
            observed_at=self._clock(), fill_price=fill_price)
        if row.outcome in _UNKNOWN_OUTCOMES:
            self._runtime.reconcile_unknown(envelope)
        else:
            self._runtime.resolve(envelope)
        self._audit("RECONCILIATION", proposal.reference_id,
                    payload={"action": "CLOSE_RECOVERY",
                             "outcome": str(envelope.payload.get("outcome")),
                             "evidence_sha256": hashlib.sha256(
                                 envelope.canonical()).hexdigest()})
        self._publish_before_send(self._clock())
        return envelope

