"""SD-137 signed, read-only /pnl recovery for uncertain Demo order outcomes.

This service has no credential or HTTP implementation. It consumes one signed
SD-064 request before calling the supplied transport and only permits the
documented Demo portfolio path. Snapshots never authorize a new order.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Protocol

from sidedeck.application.sd064_unlock_grant import UnlockAuthority, UnlockGrant
from sidedeck.application.sd036_etoro_demo_desk import EtoroDemoLineage
from sidedeck.domain.etoro_demo import DemoPortfolioSnapshot, parse_demo_portfolio
from sidedeck.domain.etoro_demo_books import (
    BaselinePosition, OrderAttribution, STRATEGY_BOOKS, reconcile_demo,
)
from sidedeck.domain.etoro_demo_orders import DEMO_PNL_PATH, require_demo_route


class PnlReadRoute(Protocol):
    def send(self, method: str, path: str, *, reference_id: str,
             body: dict[str, Any] | None = None,
             query: dict[str, str] | None = None) -> Any: ...


class PnlRecoveryRefused(PermissionError):
    """Signed read or strict portfolio evidence was not sufficient."""


@dataclass(frozen=True)
class PnlRecoveryResult:
    classification: str  # OWNED_POSITION | UNRESOLVED
    snapshot: DemoPortfolioSnapshot
    position_id: int | None
    order_id: int
    grant_id: str


def recover_from_pnl(*, route: PnlReadRoute, authority: UnlockAuthority,
                     document: Any, signature: str, subject_digest: str,
                     reference_id: str, open_reference_id: str,
                     lineage: EtoroDemoLineage,
                     baseline: tuple[BaselinePosition, ...],
                     now: datetime | None = None) -> PnlRecoveryResult:
    """Consume one owner-signed request and reconcile exact order identity.

    ``reference_id`` is unique per read (SD-064 persists use and rejects replay).
    An ``UNRESOLVED`` result means HALT/operator investigation; callers must not
    translate it into permission to submit another POST.
    """
    if not reference_id or not open_reference_id:
        raise PnlRecoveryRefused("recovery identity is invalid")
    try:
        order = lineage.order(open_reference_id)
    except ValueError as exc:
        raise PnlRecoveryRefused("recovery requires persisted SideDeck order lineage") from exc
    if (order["kind"] != "OPEN" or order["state"] != "ACCEPTED"
            or order["order_id"] is None or order["book_id"] not in STRATEGY_BOOKS.values()
            or order["instrument_id"] <= 0):
        raise PnlRecoveryRefused("recovery requires a durably accepted SideDeck open")
    order_id = int(order["order_id"])
    instrument_id = int(order["instrument_id"])
    book_id = str(order["book_id"])
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise PnlRecoveryRefused("recovery time must be timezone-aware")
    grant: UnlockGrant = authority.authorize_request(
        document=document, signature=signature, subject_digest=subject_digest,
        write=False, reference_id=reference_id, now=moment,
    )
    require_demo_route("GET", DEMO_PNL_PATH)
    payload = route.send("GET", DEMO_PNL_PATH, reference_id=reference_id)
    snapshot = parse_demo_portfolio(payload, observed_at=moment)
    snapshot.require_fresh(moment)
    # This comparison protects every baseline row and rejects foreign positions,
    # unsupported mirror holdings, and unrecognized pending orders.
    reconciled = reconcile_demo(
        snapshot, baseline=baseline,
        attributions=(OrderAttribution(order_id, book_id),), now=moment,
    )
    if reconciled.status != "MATCHED" or snapshot.pending_orders:
        return PnlRecoveryResult("UNRESOLVED", snapshot, None, order_id, grant.grant_id)
    matches = [p for p in snapshot.positions if p.order_id == order_id]
    if len(matches) > 1:
        return PnlRecoveryResult("UNRESOLVED", snapshot, None, order_id, grant.grant_id)
    if not matches:
        # A missing position does not distinguish an unfilled accepted order from
        # a position that was opened and then closed. /pnl cannot settle that lineage.
        return PnlRecoveryResult("UNRESOLVED", snapshot, None, order_id, grant.grant_id)
    position = matches[0]
    if (position.instrument_id != instrument_id or position.mirror_id != 0
            or not position.is_buy or position.leverage != 1
            or position.units <= 0 or position.units > Decimal(order["units"])
            or position.open_rate is None
            or position.open_rate > Decimal(order["limit_rate"])
            or any(p.position_id not in {base.position_id for base in baseline}
                   and p.position_id != position.position_id for p in snapshot.positions)):
        return PnlRecoveryResult("UNRESOLVED", snapshot, None, order_id, grant.grant_id)
    return PnlRecoveryResult("OWNED_POSITION", snapshot, position.position_id,
                             order_id, grant.grant_id)
