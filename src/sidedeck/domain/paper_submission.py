"""Prepared Alpaca PAPER-only order submission protocol, without live transport.

SideDeck is the order authority. This module has no live broker HTTP POST
implementation, no credential reading and no path that submits real orders.
The opt-in test dispatch requires an explicitly fixture-only write transport.
A crash/timeout leaves UNCERTAIN; never send the same order twice.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal, Mapping, Protocol

from .alpaca_paper import AlpacaPaperReadClient, PaperGetTransport
from .alpaca_paper_execution import _order
from .alpaca_paper_pair import DualPaperAccountInspector
from .paper_desk import BROKER_KEY_SLOTS, PaperDeskError, PaperOrderDraft
from .paper_outbox import DurablePaperDesk

MAX_DRAFT_AGE = timedelta(seconds=60)


class PaperCreateTransport(Protocol):
    """Injected **test fixture only** POST-compatible surface; no network."""

    fixture_only: Literal[True]

    def post(self, path: str, payload: Mapping[str, str | bool]) -> tuple[int, object]: ...


@dataclass(frozen=True)
class PaperSubmissionPreview:
    portfolio_id: str
    key_slot: str
    client_order_id: str
    paper_endpoint: Literal["/v2/orders"]
    preview: dict[str, str | bool]
    accounts_distinct: bool
    status: Literal["READY_FOR_OFFLINE_FIXTURE", "ALREADY_ATTEMPTED"]
    broker_write_enabled: Literal[False] = False


@dataclass(frozen=True)
class PaperSubmissionResult:
    client_order_id: str
    outcome: Literal["FIXTURE_ACKNOWLEDGED", "UNCERTAIN_CHECK_PAPER_GET"]
    network_requests: Literal[0] = 0
    real_paper_orders: Literal[0] = 0


class SideDeckPaperSubmission:
    """Provider-agnostic contract for eventual controlled PAPER writes.

    Production use remains impossible: the only accepted write transport is
    a fixture class, and a persistent DB kill switch stays ENGAGED. A future
    owner-approved production transport/permit is a separate implementation.
    """

    def __init__(
        self,
        desk: DurablePaperDesk,
        first_paper: PaperGetTransport,
        second_paper: PaperGetTransport,
    ) -> None:
        self._desk = desk
        self._first = first_paper
        self._second = second_paper

    def _validate(
        self, order_id: str, *, key_slot: str, now: datetime,
    ) -> PaperOrderDraft:
        if now.tzinfo is None or now.utcoffset() is None:
            raise PaperDeskError("paper submission clock must be UTC-aware")
        draft, broker_order = self._desk.order_binding(order_id)
        if (
            key_slot not in BROKER_KEY_SLOTS.values()
            or BROKER_KEY_SLOTS[draft.portfolio_id] != key_slot
            or draft.key_slot != key_slot
        ):
            raise PaperDeskError("paper submission crosses strategy key slots")
        if broker_order is not None:
            raise PaperDeskError("paper order already has broker acknowledgement")
        if draft.submission_enabled:
            raise PaperDeskError("stored draft unexpectedly permits auto submission")
        age = now.astimezone(timezone.utc) - draft.created_at.astimezone(timezone.utc)
        if age < timedelta(0) or age > MAX_DRAFT_AGE:
            raise PaperDeskError("paper order risk/price verification is stale")
        return draft

    def preview(
        self, order_id: str, *, key_slot: str, now: datetime,
    ) -> PaperSubmissionPreview:
        draft = self._validate(order_id, key_slot=key_slot, now=now)
        accounts = DualPaperAccountInspector(self._first, self._second).inspect()
        if not (accounts.two_accounts_verified and accounts.both_active and accounts.both_unblocked):
            raise PaperDeskError("two distinct active unblocked paper accounts required")
        status = self._desk.paper_submission_status(order_id)
        return PaperSubmissionPreview(
            portfolio_id=draft.portfolio_id,
            key_slot=draft.key_slot,
            client_order_id=draft.client_order_id,
            paper_endpoint="/v2/orders",
            preview=draft.alpaca_preview(),
            accounts_distinct=True,
            status=("READY_FOR_OFFLINE_FIXTURE" if status == "NOT_SENT"
                    else "ALREADY_ATTEMPTED"),
        )

    def submit_fixture_once(
        self, order_id: str, *, key_slot: str, now: datetime,
        writer: PaperCreateTransport,
    ) -> PaperSubmissionResult:
        """Exactly one **synthetic** POST to an injected fixture writer.

        A durable UNCERTAIN state is committed before the fixture operation,
        then a validated acknowledgement is committed. A failed/unknown
        result is left UNCERTAIN; subsequent calls cannot repeat the POST.
        """
        if getattr(writer, "fixture_only", False) is not True:
            raise PaperDeskError("PAPER broker writing remains disabled")
        ready = self.preview(order_id, key_slot=key_slot, now=now)
        if ready.status != "READY_FOR_OFFLINE_FIXTURE":
            raise PaperDeskError("paper request already attempted; do not retry")
        # This label is NOT a broker account ID. It's only a local fixture
        # dispatch slot and cannot certify real account provenance.
        binding = f"OFFLINE_FIXTURE:{ready.portfolio_id}"
        self._desk.stage_paper_submission(
            order_id, key_slot=key_slot,
            account_fingerprint=binding, now=now,
        )
        try:
            status, payload = writer.post("/v2/orders", ready.preview)
            if status not in (200, 201):
                return PaperSubmissionResult(order_id, "UNCERTAIN_CHECK_PAPER_GET")
            draft = self._desk.order_draft(order_id)
            parsed = _order(payload, draft)
            self._desk.record_paper_acknowledgement(
                order_id, broker_order_id=parsed.order_id, key_slot=key_slot,
                account_fingerprint=binding,
            )
            return PaperSubmissionResult(order_id, "FIXTURE_ACKNOWLEDGED")
        except Exception:
            # A timeout/exception can occur *after* remote acceptance.
            # Deliberately never retry or change the UNCERTAIN journal.
            return PaperSubmissionResult(order_id, "UNCERTAIN_CHECK_PAPER_GET")

    def reconcile_uncertain_fixture(
        self, order_id: str, *, key_slot: str, now: datetime,
        paper_reader: PaperGetTransport,
    ) -> PaperSubmissionResult:
        """Recover an uncertain fixture by GET client_order_id only.

        Does not submit an order; never retries a failed 404/401/403 lookup.
        A future production recovery path needs independent account binding.
        """
        if self._desk.paper_submission_status(order_id) != "UNCERTAIN":
            raise PaperDeskError("paper order is not awaiting recovery")
        draft = self._validate(order_id, key_slot=key_slot, now=now)
        result = AlpacaPaperReadClient(paper_reader)._get(
            "/v2/orders:by_client_order_id",
            {"client_order_id": draft.client_order_id},
        )
        parsed = _order(result, draft)
        self._desk.record_paper_acknowledgement(
            order_id, broker_order_id=parsed.order_id, key_slot=key_slot,
            account_fingerprint=f"OFFLINE_FIXTURE:{draft.portfolio_id}",
        )
        return PaperSubmissionResult(order_id, "FIXTURE_ACKNOWLEDGED")
