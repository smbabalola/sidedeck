from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

from .accounting import Ledger, fill_event
from .contracts import EventType, Side, TradeIntent
from .risk import RiskDecision


@dataclass(frozen=True)
class SimulatedFill:
    fill_id: UUID
    order_id: UUID
    intent_id: UUID
    portfolio_id: str
    instrument_id: str
    side: Side
    quantity: Decimal
    price: Decimal
    fee: Decimal
    occurred_at: datetime
    status: str = "SIMULATED_LOCAL"


@dataclass
class SimulatedOrder:
    order_id: UUID
    portfolio_id: str
    instrument_id: str
    side: Side
    requested_quantity: Decimal
    filled_quantity: Decimal = Decimal("0")
    status: str = "PROPOSED"

    def apply_fill(self, quantity: Decimal) -> None:
        if self.status in {"CANCELLED", "FILLED"}:
            raise ValueError("cannot fill a closed simulated order")
        if quantity <= 0 or self.filled_quantity + quantity > self.requested_quantity:
            raise ValueError("fill quantity exceeds the simulated order")
        self.filled_quantity += quantity
        self.status = "FILLED" if self.filled_quantity == self.requested_quantity else "PARTIALLY_FILLED"

    def cancel(self) -> None:
        if self.status == "FILLED":
            raise ValueError("cannot cancel a filled simulated order")
        if self.status == "CANCELLED":
            return
        self.status = "CANCELLED"


class LocalArtifactStore:
    """Small restart-safe JSON store for demo lineage; never connects externally."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write({"orders": [], "fills": [], "risk_decisions": [], "runs": []})

    def load(self) -> dict[str, Any]:
        return cast(dict[str, Any], json.loads(self.path.read_text(encoding="utf-8")))

    def append(self, section: str, value: dict[str, Any]) -> None:
        payload = self.load()
        payload.setdefault(section, []).append(value)
        self._write(payload)

    def replace(self, payload: dict[str, Any]) -> None:
        self._write(payload)

    def _write(self, payload: dict[str, Any]) -> None:
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        temporary.replace(self.path)


class LocalExecutionSimulator:
    def __init__(self, *, fee_rate: Decimal = Decimal("0.001"), spread_bps: Decimal = Decimal("5")) -> None:
        self.fee_rate = fee_rate
        self.spread_bps = spread_bps

    def execute(
        self,
        ledger: Ledger,
        intent: TradeIntent,
        decision: RiskDecision,
        snapshot_price: Decimal,
        occurred_at: datetime,
        *,
        fill_ratio: Decimal = Decimal("1"),
    ) -> tuple[UUID, SimulatedFill | None]:
        order_id = uuid4()
        if not decision.accepted:
            return order_id, None
        if fill_ratio <= 0 or fill_ratio > 1:
            raise ValueError("fill ratio must be in (0, 1]")
        quantity = (intent.quantity or Decimal("0")) * fill_ratio
        quantity = quantity.quantize(Decimal("1"), rounding=ROUND_DOWN)
        if quantity <= 0:
            return order_id, None
        side_factor = Decimal("1") + self.spread_bps / Decimal("10000")
        price = snapshot_price * (side_factor if intent.side is Side.BUY else Decimal("2") - side_factor)
        state = ledger.replay(intent.portfolio_id)
        fee = (quantity * price * self.fee_rate).quantize(Decimal("0.01"))
        cost_basis = None
        event_type = EventType.BUY_FILL
        if intent.side is Side.SELL:
            position = state.positions.get(intent.instrument_id)
            if position is None:
                raise ValueError("cannot simulate a sale without a position")
            cost_basis = position.cost_basis / position.quantity * quantity
            event_type = EventType.SELL_FILL
        event = fill_event(
            intent.portfolio_id,
            f"simulated:{intent.experiment_id}:{intent.strategy_id}:{occurred_at.isoformat()}:{intent.instrument_id}:{intent.side}",
            event_type,
            intent.instrument_id,
            quantity,
            price,
            occurred_at,
            fee,
            cost_basis,
        )
        ledger.append(event)
        fill = SimulatedFill(
            fill_id=uuid4(), order_id=order_id, intent_id=decision.intent_id,
            portfolio_id=intent.portfolio_id, instrument_id=intent.instrument_id,
            side=intent.side, quantity=quantity, price=price, fee=fee,
            occurred_at=occurred_at,
        )
        return order_id, fill
