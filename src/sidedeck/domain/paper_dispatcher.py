"""SideDeck PAPER dispatcher: one guarded write path, OFF in shipped config.

Binds each paper GET and POST transport to the same in-memory key pair.
A durable UNCERTAIN claim is recorded before the POST; no automatic retry
or market/live endpoint exists. This is *not* invoked by any product CLI.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from sidedeck.paper import AlpacaPaperHttpTransport, PaperCredentials

from . import alpaca_paper_http_post as post_api
from .alpaca_paper import AlpacaPaperReadClient
from .alpaca_paper_execution import _order
from .alpaca_paper_http_post import AlpacaPaperPostTransport, PaperOrderPermit, RestrictedPaperAuth
from .paper_desk import BROKER_KEY_SLOTS, PaperDeskError
from .paper_outbox import DurablePaperDesk
from .paper_post_contract import validate_paper_post_draft
from .paper_submission import MAX_DRAFT_AGE, SideDeckPaperSubmission


@dataclass(frozen=True)
class PaperDispatchResult:
    portfolio_id: str
    key_slot: str
    client_order_id: str
    outcome: Literal["ACKNOWLEDGED", "UNCERTAIN_CHECK_BY_CLIENT_ORDER_ID"]
    # No broker identity, private account data or raw HTTP response.
    write_transport: Literal["ALPACA_PAPER_ONLY"] = "ALPACA_PAPER_ONLY"


class GuardedPaperDispatcher:
    """Production transport *wiring*, intentionally unreachable while disabled.

    The caller cannot override the network kill switch through a constructor
    flag, environment variable, command line, or a provided API URL.
    """

    def __init__(
        self, desk: DurablePaperDesk,
        tradingagents: PaperCredentials,
        ai_trading: PaperCredentials,
    ) -> None:
        if (
            not tradingagents.api_key or not tradingagents.secret_key
            or not ai_trading.api_key or not ai_trading.secret_key
            or tradingagents.api_key == ai_trading.api_key
        ):
            raise PaperDeskError("paper key pairs missing or identical")
        self._desk = desk
        self._readers = (
            AlpacaPaperHttpTransport(tradingagents),
            AlpacaPaperHttpTransport(ai_trading),
        )
        self._writers = {
            "ALPACA_API_KEY": AlpacaPaperPostTransport(
                RestrictedPaperAuth(tradingagents.api_key, tradingagents.secret_key)
            ),
            "ALPACA_API_KEY2": AlpacaPaperPostTransport(
                RestrictedPaperAuth(ai_trading.api_key, ai_trading.secret_key)
            ),
        }
        self._intent = SideDeckPaperSubmission(
            desk, self._readers[0], self._readers[1]
        )

    @staticmethod
    def _assert_permit(
        permit: PaperOrderPermit, *, key_slot: str,
        client_order_id: str, now: datetime,
    ) -> None:
        if now.tzinfo is None or now.utcoffset() is None:
            raise PaperDeskError("dispatch clock must be timezone-aware")
        if permit.expires_at.tzinfo is None or permit.expires_at.utcoffset() is None:
            raise PaperDeskError("owner permit expiry must be timezone-aware")
        if not (
            permit.owner_confirmed and permit.verified_account_slot
            and permit.key_slot == key_slot
            and permit.client_order_id == client_order_id
            and now.astimezone(timezone.utc) <= permit.expires_at.astimezone(timezone.utc)
        ):
            raise PaperDeskError("order-scoped paper execution permit is invalid")

    def dispatch(
        self, client_order_id: str, *, key_slot: str,
        permit: PaperOrderPermit, now: datetime,
    ) -> PaperDispatchResult:
        """A single potential POST; fail BEFORE any GET when writes are off."""
        if not post_api.NETWORK_PAPER_WRITES_ENABLED:
            raise PaperDeskError("paper broker writes remain disabled")
        self._assert_permit(
            permit, key_slot=key_slot, client_order_id=client_order_id, now=now,
        )
        if self._desk.paper_submission_status(client_order_id) != "NOT_SENT":
            raise PaperDeskError("order already attempted: reconcile; never resend")
        ready = self._intent.preview(client_order_id, key_slot=key_slot, now=now)
        if ready.status != "READY_FOR_OFFLINE_FIXTURE":
            raise PaperDeskError("paper order already attempted")
        draft, prior_order = self._desk.order_binding(client_order_id)
        if (
            prior_order is not None
            or BROKER_KEY_SLOTS.get(draft.portfolio_id) != key_slot
        ):
            raise PaperDeskError("paper order has invalid strategy binding")
        validate_paper_post_draft(draft)
        if now.astimezone(timezone.utc) - draft.created_at > MAX_DRAFT_AGE:
            raise PaperDeskError("paper decision stale at dispatch")
        # Durable claim is committed before opening any broker POST. This
        # prevents duplicates even if an exception occurs after acceptance.
        # The slot marker is NOT a proven broker account fingerprint.
        binding = f"KEY_SLOT_CHECKED:{key_slot}"
        self._desk.stage_paper_submission(
            client_order_id, key_slot=key_slot,
            account_fingerprint=binding, now=now,
        )
        try:
            status, payload = self._writers[key_slot].send(
                draft, permit=permit, now=now,
            )
            if status not in (200, 201):
                return PaperDispatchResult(
                    draft.portfolio_id, key_slot, client_order_id,
                    "UNCERTAIN_CHECK_BY_CLIENT_ORDER_ID",
                )
            accepted = _order(payload, draft)
            self._desk.record_paper_acknowledgement(
                client_order_id, broker_order_id=accepted.order_id,
                key_slot=key_slot, account_fingerprint=binding,
            )
            return PaperDispatchResult(
                draft.portfolio_id, key_slot, client_order_id, "ACKNOWLEDGED",
            )
        except Exception:
            # It is unsafe to infer an order was rejected after a timeout.
            # The existing durable claim remains UNCERTAIN on every failure.
            return PaperDispatchResult(
                draft.portfolio_id, key_slot, client_order_id,
                "UNCERTAIN_CHECK_BY_CLIENT_ORDER_ID",
            )

    def recover_uncertain(
        self, client_order_id: str, *, key_slot: str,
        read_only_authorized: bool = False,
    ) -> PaperDispatchResult:
        """GET-only recovery, including after days of uncertain delivery.

        Never requires a fresh trade price: this call *cannot send* an order.
        Never retries an unavailable 404/403 read. Existing UNCERTAIN survives.
        """
        if not read_only_authorized:
            raise PaperDeskError("explicit read-only paper recovery permission required")
        if self._desk.paper_submission_status(client_order_id) != "UNCERTAIN":
            raise PaperDeskError("paper order is not awaiting recovery")
        draft, prior = self._desk.order_binding(client_order_id)
        if (
            prior is not None
            or BROKER_KEY_SLOTS.get(draft.portfolio_id) != key_slot
            or draft.key_slot != key_slot
        ):
            raise PaperDeskError("paper recovery account binding mismatch")
        reader = self._readers[0] if key_slot == "ALPACA_API_KEY" else self._readers[1]
        response = AlpacaPaperReadClient(reader)._get(
            "/v2/orders:by_client_order_id",
            {"client_order_id": draft.client_order_id},
        )
        broker_order = _order(response, draft)
        self._desk.record_paper_acknowledgement(
            client_order_id, broker_order_id=broker_order.order_id,
            key_slot=key_slot, account_fingerprint=f"KEY_SLOT_CHECKED:{key_slot}",
        )
        return PaperDispatchResult(
            draft.portfolio_id, key_slot, client_order_id, "ACKNOWLEDGED",
        )
