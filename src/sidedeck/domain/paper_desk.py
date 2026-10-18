"""SideDeck-owned Alpaca PAPER order planning and fill reconciliation.

OFFLINE ONLY: no HTTP, credentials, order submission or cancellation. Real
broker integrations must later provide authenticated paper-account binding,
durable order outbox and independently accepted write authorisation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from enum import StrEnum
import hashlib
import json
from typing import Any, Literal
from uuid import UUID, NAMESPACE_URL, uuid5

from .accounting import Ledger, PortfolioState, fill_event
from .contracts import AUTHORIZED_PORTFOLIOS, EventType, MarketSnapshot, Side, TradeIntent, require_utc
from .instruments import get_instrument_by_id, validate_quantity
from .risk import RiskDecision, RiskGate

BROKER_KEY_SLOTS = {
    "tradingagents": "ALPACA_API_KEY",
    "ai-trading": "ALPACA_API_KEY2",
}
CENT = Decimal("0.01")
MAX_PAPER_ALLOCATION = Decimal("1000")


class PaperDeskError(ValueError):
    """The plan or fill violates SideDeck's isolated paper portfolio contract."""


class DeskOrderStatus(StrEnum):
    PREPARED = "PREPARED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class PaperOrderDraft:
    """Proposed request payload. It is NEVER submitted by this module."""

    portfolio_id: str
    strategy_id: str
    key_slot: Literal["ALPACA_API_KEY", "ALPACA_API_KEY2"]
    client_order_id: str
    local_order_id: UUID
    instrument_id: str
    symbol: str
    side: Literal["buy", "sell"]
    quantity: Decimal
    limit_price: Decimal
    created_at: datetime
    risk_reason: str
    risk_policy_version: str
    model_revision: str
    submission_enabled: bool = False

    def alpaca_preview(self) -> dict[str, str | bool]:
        """Display safe, unsubmitted paper-only limit/day request fields."""
        return {
            "symbol": self.symbol,
            "side": self.side,
            "qty": str(self.quantity),
            "type": "limit",
            "time_in_force": "day",
            "limit_price": str(self.limit_price),
            "extended_hours": False,
            "client_order_id": self.client_order_id,
        }


@dataclass(frozen=True)
class PaperFillEvidence:
    """Parsed broker fill evidence, not an AI guess or a snapshot delta."""

    client_order_id: str
    broker_order_id: str
    broker_fill_id: str
    portfolio_id: str
    key_slot: Literal["ALPACA_API_KEY", "ALPACA_API_KEY2"]
    symbol: str
    side: Literal["buy", "sell"]
    quantity: Decimal
    price: Decimal
    fee: Decimal
    occurred_at: datetime


@dataclass
class PaperOrderTrack:
    draft: PaperOrderDraft
    status: DeskOrderStatus = DeskOrderStatus.PREPARED
    broker_order_id: str | None = None
    filled_quantity: Decimal = Decimal("0")
    evidence_by_fill_id: dict[str, PaperFillEvidence] = field(default_factory=dict)


@dataclass(frozen=True)
class FillReconciliation:
    portfolio_id: str
    client_order_id: str
    applied: bool
    cumulative_quantity: Decimal
    order_status: DeskOrderStatus
    # No provider account ID or authentication information.


class SideDeckPaperDesk:
    """An in-process planning/reconciliation boundary, never a broker API.

    This prototype's order tracks are in-memory only. A durable transactional
    order outbox is required before any future live PAPER submission.
    """

    def __init__(self, risk_gate: RiskGate | None = None) -> None:
        self._risk_gate = risk_gate or RiskGate()
        self._orders: dict[str, PaperOrderTrack] = {}
        self._active_by_portfolio: dict[str, str] = {}

    @property
    def paper_write_enabled(self) -> bool:
        return False

    def prepare(
        self, intent: TradeIntent, state: PortfolioState,
        snapshot: MarketSnapshot, *, marks: dict[str, MarketSnapshot],
    ) -> tuple[PaperOrderDraft, RiskDecision]:
        """Reject unsafe AI proposals; reserve one pending order per strategy."""
        if intent.portfolio_id not in AUTHORIZED_PORTFOLIOS:
            raise PaperDeskError("portfolio is not authorised")
        if state.portfolio_id != intent.portfolio_id:
            raise PaperDeskError("portfolio ledger identity mismatch")
        if intent.side is Side.HOLD:
            raise PaperDeskError("HOLD cannot become a broker order")
        if intent.quantity is None or intent.notional_usd is not None:
            raise PaperDeskError("PAPER preview requires explicit whole-share quantity")
        if snapshot.instrument_id != intent.instrument_id:
            raise PaperDeskError("instrument does not match approved market snapshot")
        if snapshot.instrument_id not in marks or marks[snapshot.instrument_id] != snapshot:
            raise PaperDeskError("missing or different current mark")
        instrument = get_instrument_by_id(intent.instrument_id)
        try:
            validate_quantity(instrument, intent.quantity)
            cutoff = require_utc(intent.decision_timestamp)
            nav = state.nav(
                marks, cutoff,
                timedelta(seconds=self._risk_gate.policy.max_snapshot_age_seconds),
            )
        except ValueError as exc:
            raise PaperDeskError("portfolio holdings or market marks invalid") from exc
        risk = self._risk_gate.evaluate(
            intent, state, snapshot, portfolio_value=nav, marks=marks,
        )
        if not risk.accepted:
            raise PaperDeskError(f"SideDeck risk gate refused proposed order: {risk.reason}")
        # ROUND_DOWN on buys / ROUND_UP on sells produces no-worse limits
        # than the observed price. This may not fill; never use a market order.
        rounding = ROUND_DOWN if intent.side is Side.BUY else ROUND_UP
        limit_price = snapshot.price.quantize(CENT, rounding=rounding)
        if limit_price <= 0:
            raise PaperDeskError("limit price rounds to zero")
        if intent.side is Side.BUY and state.cash < (
            intent.quantity * limit_price + (
                intent.quantity * limit_price * self._risk_gate.policy.fee_rate
            ).quantize(CENT, rounding=ROUND_UP)
        ):
            raise PaperDeskError("cash cannot fund full limit price plus conservative fees")

        canonical = json.dumps({
            "intent": intent.model_dump(mode="json"),
            "market": snapshot.model_dump(mode="json"),
            "limit": str(limit_price),
            "key_slot": BROKER_KEY_SLOTS[intent.portfolio_id],
        }, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(canonical.encode()).hexdigest()
        prefix = "ta" if intent.portfolio_id == "tradingagents" else "ai"
        client_id = f"sd-{prefix}-{digest[:32]}"
        prior = self._orders.get(client_id)
        if prior:
            if prior.draft.portfolio_id != intent.portfolio_id:
                raise PaperDeskError("client-order id collision across portfolios")
            return prior.draft, risk
        if intent.portfolio_id in self._active_by_portfolio:
            raise PaperDeskError("another paper order is unresolved for this strategy")

        draft = PaperOrderDraft(
            portfolio_id=intent.portfolio_id,
            strategy_id=intent.strategy_id,
            key_slot=BROKER_KEY_SLOTS[intent.portfolio_id],  # type: ignore[arg-type]
            client_order_id=client_id,
            local_order_id=uuid5(NAMESPACE_URL, client_id),
            instrument_id=intent.instrument_id,
            symbol=instrument.ticker,
            side="buy" if intent.side is Side.BUY else "sell",
            quantity=intent.quantity,
            limit_price=limit_price,
            created_at=cutoff,
            risk_reason=str(risk.reason),
            risk_policy_version=risk.policy_version,
            model_revision=intent.model_revision,
        )
        self._orders[client_id] = PaperOrderTrack(draft=draft)
        self._active_by_portfolio[intent.portfolio_id] = client_id
        return draft, risk

    def acknowledge(self, client_order_id: str, *, broker_order_id: str) -> None:
        """Attach a matching future PAPER broker order acknowledgment offline."""
        track = self._track(client_order_id)
        if not broker_order_id or len(broker_order_id) > 200:
            raise PaperDeskError("invalid broker order identifier")
        if track.broker_order_id is not None:
            if track.broker_order_id == broker_order_id:
                return
            raise PaperDeskError("paper order is already bound to a different broker order")
        if track.status is not DeskOrderStatus.PREPARED:
            raise PaperDeskError("only prepared orders can be acknowledged")
        track.broker_order_id = broker_order_id
        track.status = DeskOrderStatus.ACKNOWLEDGED

    def reconcile_fill(
        self, evidence: PaperFillEvidence, ledger: Ledger,
    ) -> FillReconciliation:
        """Append verified PAPER fill only to matching strategy's local ledger."""
        track = self._track(evidence.client_order_id)
        draft = track.draft
        if not track.broker_order_id or track.broker_order_id != evidence.broker_order_id:
            raise PaperDeskError("fill is not tied to acknowledged paper order")
        if (
            evidence.portfolio_id != draft.portfolio_id or
            evidence.key_slot != draft.key_slot or
            evidence.symbol != draft.symbol or
            evidence.side != draft.side
        ):
            raise PaperDeskError("broker fill crosses portfolio, credential or instrument")
        if not evidence.broker_fill_id or len(evidence.broker_fill_id) > 200:
            raise PaperDeskError("broker fill identity is invalid")
        if not evidence.quantity.is_finite() or evidence.quantity <= 0:
            raise PaperDeskError("invalid fill quantity")
        if not evidence.price.is_finite() or evidence.price <= 0:
            raise PaperDeskError("invalid fill price")
        if not evidence.fee.is_finite() or evidence.fee < 0:
            raise PaperDeskError("invalid fill fees")
        if evidence.side == "buy" and evidence.price > draft.limit_price:
            raise PaperDeskError("paper buy execution exceeds limit")
        if evidence.side == "sell" and evidence.price < draft.limit_price:
            raise PaperDeskError("paper sell execution below limit")
        if require_utc(evidence.occurred_at) < draft.created_at:
            raise PaperDeskError("fill predates strategy order")
        previous = track.evidence_by_fill_id.get(evidence.broker_fill_id)
        if previous:
            if previous != evidence:
                raise PaperDeskError("same broker fill id has conflicting payload")
            return FillReconciliation(
                draft.portfolio_id, draft.client_order_id, False,
                track.filled_quantity, track.status,
            )
        if track.status in {DeskOrderStatus.CANCELLED, DeskOrderStatus.FILLED}:
            raise PaperDeskError("closed paper order cannot accept new fills")
        if track.filled_quantity + evidence.quantity > draft.quantity:
            raise PaperDeskError("paper fill over-executes approved quantity")

        state = ledger.replay(draft.portfolio_id)
        if evidence.side == "buy":
            gross = evidence.quantity * evidence.price + evidence.fee
            if gross > state.cash:
                raise PaperDeskError("paper fill exceeds isolated strategy cash")
            event_type = EventType.BUY_FILL
            cost_basis = None
        else:
            existing = state.positions.get(draft.instrument_id)
            if existing is None or evidence.quantity > existing.quantity:
                raise PaperDeskError("paper fill would sell unowned shares")
            if evidence.fee > evidence.quantity * evidence.price:
                raise PaperDeskError("paper sell proceeds cannot cover fees")
            event_type = EventType.SELL_FILL
            cost_basis = existing.cost_basis / existing.quantity * evidence.quantity

        key = f"alpaca-paper-fill:{draft.portfolio_id}:{evidence.broker_fill_id}"
        event = fill_event(
            draft.portfolio_id, key, event_type, draft.instrument_id,
            evidence.quantity, evidence.price, evidence.occurred_at,
            evidence.fee, cost_basis,
        )
        event = event.model_copy(update={
            "operation_id": uuid5(NAMESPACE_URL, key),
            "causation_id": draft.local_order_id,
            "metadata": {
                "source": "ALPACA_PAPER_FILL_EVIDENCE",
                "strategy_id": draft.strategy_id,
                "client_order_id": draft.client_order_id,
                "broker_fill_id": evidence.broker_fill_id,
            },
        })
        # Ledger enforces balanced postings and can be persisted through the
        # existing event store by an authorised, future orchestration layer.
        ledger.append(event)
        track.evidence_by_fill_id[evidence.broker_fill_id] = evidence
        track.filled_quantity += evidence.quantity
        track.status = (
            DeskOrderStatus.FILLED
            if track.filled_quantity == draft.quantity
            else DeskOrderStatus.PARTIALLY_FILLED
        )
        if track.status is DeskOrderStatus.FILLED:
            self._active_by_portfolio.pop(draft.portfolio_id, None)
        return FillReconciliation(
            draft.portfolio_id, draft.client_order_id, True,
            track.filled_quantity, track.status,
        )

    def close_unfilled(self, client_order_id: str) -> None:
        """Close local book only after a verified external cancellation."""
        track = self._track(client_order_id)
        if track.status is DeskOrderStatus.FILLED:
            raise PaperDeskError("cannot cancel a fully filled order")
        if track.status is DeskOrderStatus.CANCELLED:
            return
        track.status = DeskOrderStatus.CANCELLED
        self._active_by_portfolio.pop(track.draft.portfolio_id, None)

    def _track(self, client_order_id: str) -> PaperOrderTrack:
        try:
            return self._orders[client_order_id]
        except KeyError as exc:
            raise PaperDeskError("unknown SideDeck paper order") from exc
