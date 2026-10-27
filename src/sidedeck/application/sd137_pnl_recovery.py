"""SD-137 signed, read-only /pnl recovery for uncertain Demo order outcomes.

This service has no credential or HTTP implementation. It consumes one signed
SD-064 request before calling the supplied transport and only permits the
documented Demo portfolio path. Snapshots never authorize a new order.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from sidedeck.application.sd064_unlock_grant import UnlockAuthority, UnlockGrant
from sidedeck.application.sd036_etoro_demo_desk import EtoroDemoDesk
from sidedeck.domain.etoro_demo_books import EtoroDemoBookError
from sidedeck.domain.etoro_demo import DemoPortfolioSnapshot, parse_demo_portfolio
from sidedeck.domain.etoro_demo_orders import (
    DEMO_PNL_PATH, EtoroDemoOrderError, require_demo_route,
)


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
                     desk: EtoroDemoDesk,
                     now: datetime | None = None) -> PnlRecoveryResult:
    """Consume one owner-signed request and reconcile exact order identity.

    ``reference_id`` is unique per read (SD-064 persists use and rejects replay).
    An ``UNRESOLVED`` result means HALT/operator investigation; callers must not
    translate it into permission to submit another POST.
    """
    if not reference_id or not open_reference_id:
        raise PnlRecoveryRefused("recovery identity is invalid")
    try:
        order = desk.accepted_open_snapshot_identity(open_reference_id)
    except EtoroDemoOrderError as exc:
        raise PnlRecoveryRefused("recovery requires a durably accepted SideDeck open") from exc
    order_id = int(order["order_id"])
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
    try:
        # Existing desk code enforces exact lineage, baseline immutability,
        # price/quantity/side/leverage, position registration, outbox fill and HALT.
        position = desk.recover_open_from_snapshot(
            open_reference_id, snapshot=snapshot, now=moment,
        )
    except (EtoroDemoOrderError, EtoroDemoBookError):
        return PnlRecoveryResult("UNRESOLVED", snapshot, None, order_id, grant.grant_id)
    return PnlRecoveryResult("OWNED_POSITION", snapshot, position.position_id,
                             order_id, grant.grant_id)
