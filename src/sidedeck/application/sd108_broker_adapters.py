"""SD-108 adapters from recorded eToro Demo responses to SD-074 envelopes.

The adapters deliberately stop at the trusted-input boundary.  They do not own a
transport, read credentials, or decide whether a proposal may be submitted.  A
caller supplies a response already obtained by an approved transport (or an
offline fixture); the adapter applies the existing strict eToro parser and seals
only the normalized fields consumed by ``InputVerifier``.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sidedeck.application.sd074_trusted_inputs import Envelope, SourceSigner
from sidedeck.domain.etoro_demo_orders import (
    CloseAcceptance,
    DemoCloseRequest,
    DemoOpenRequest,
    EtoroDemoOrderError,
    FreshQuote,
    OpenAcceptance,
    parse_close_acceptance,
    parse_close_info,
    parse_fresh_quote,
    parse_open_acceptance,
    parse_order_lookup,
)


class BrokerAdapterError(ValueError):
    """A broker response cannot be safely converted into trusted evidence."""


_REFERENCE = re.compile(r"[0-9a-f]{32}")


def _proposal_reference(value: str) -> str:
    """Use the policy ledger's 32-hex reference form for UUID-shaped order ids."""
    if _REFERENCE.fullmatch(value):
        return value
    try:
        return uuid.UUID(value).hex
    except (ValueError, AttributeError):
        raise BrokerAdapterError("reference id is not a proposal reference") from None


def _utc(moment: datetime, name: str) -> datetime:
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise BrokerAdapterError(f"{name} must be timezone-aware")
    return moment.astimezone(timezone.utc)


def response_sha256(payload: Mapping[str, Any]) -> str:
    """Hash the exact JSON response shape used by the reconciliation envelope."""
    if type(payload) is not dict:
        raise BrokerAdapterError("broker response must be a plain JSON object")
    try:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                              allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, RecursionError):
        raise BrokerAdapterError("broker response is not canonical JSON") from None
    return hashlib.sha256(encoded).hexdigest()


class EtoroDemoQuoteAdapter:
    """Normalize one strict eToro rates response into a broker quote envelope."""

    def __init__(self, signer: SourceSigner, *, canonical_id: str,
                 allow_naive_utc: bool = False) -> None:
        if not canonical_id or ":" not in canonical_id:
            raise BrokerAdapterError("canonical instrument id is required")
        self._signer = signer
        self._canonical_id = canonical_id
        self._allow_naive_utc = allow_naive_utc

    def seal(self, payload: Mapping[str, Any], *, instrument_id: int,
             now: datetime) -> Envelope:
        try:
            quote = parse_fresh_quote(payload, instrument_id=instrument_id,
                                      now=_utc(now, "now"),
                                      allow_naive_utc=self._allow_naive_utc)
        except (EtoroDemoOrderError, TypeError, ValueError) as exc:
            raise BrokerAdapterError(str(exc)) from None
        return self._seal_quote(quote)

    def _seal_quote(self, quote: FreshQuote) -> Envelope:
        return self._signer.seal({
            "canonical_id": self._canonical_id,
            "bid": str(quote.bid),
            "ask": str(quote.ask),
            "quote_time": quote.observed_at.astimezone(timezone.utc).isoformat(),
        })


class EtoroDemoReconciliationAdapter:
    """Normalize a strict open-order lookup into one SD-074 fill envelope.

    The lookup digest and broker order id are carried into the envelope, so a
    later resolver can prove which response accounted for the proposal.  Multiple
    executions are reduced to a Decimal weighted average; no float arithmetic is
    used.  A non-terminal lookup with no execution is kept ``UNRESOLVED`` so the
    policy ledger can reserve the proposal and trip its existing recovery path.
    """

    def __init__(self, signer: SourceSigner) -> None:
        self._signer = signer

    def parse_open_acceptance(self, payload: Mapping[str, Any], *,
                              request: DemoOpenRequest) -> OpenAcceptance:
        """Validate acceptance as an order reference only; acceptance is never a fill."""
        try:
            return parse_open_acceptance(payload, reference_id=request.reference_id)
        except (EtoroDemoOrderError, TypeError, ValueError) as exc:
            raise BrokerAdapterError(str(exc)) from None

    def parse_close_acceptance(self, payload: Mapping[str, Any], *,
                               request: DemoCloseRequest) -> CloseAcceptance:
        """Bind a close acceptance to the requested SideDeck position and instrument."""
        try:
            return parse_close_acceptance(payload, request=request)
        except (EtoroDemoOrderError, TypeError, ValueError) as exc:
            raise BrokerAdapterError(str(exc)) from None

    def seal_open_lookup(self, payload: Mapping[str, Any], *, request: DemoOpenRequest,
                         observed_at: datetime, order_id: int | None = None) -> Envelope:
        at = _utc(observed_at, "observed_at")
        try:
            outcome = parse_order_lookup(payload, request=request, order_id=order_id)
        except (EtoroDemoOrderError, TypeError, ValueError) as exc:
            raise BrokerAdapterError(str(exc)) from None

        units = outcome.filled_units
        position_ids = {str(e.position_id) for e in outcome.executions}
        if units and len(position_ids) != 1:
            # The current SD-063 ledger stores one broker position lineage per order.  Until
            # multi-position close management is implemented, retain the response digest and
            # halt for manual reconciliation instead of collapsing distinct positions.
            status, units, price = "UNRESOLVED", Decimal("0"), Decimal("0")
        elif units:
            weighted = sum((execution.units * execution.avg_price
                            for execution in outcome.executions), Decimal("0"))
            price = weighted / units
            status = "FILLED" if outcome.status == "FILLED" else "PARTIALLY_FILLED"
        else:
            price = Decimal("0")
            status = "NOT_FILLED" if outcome.terminal else "UNRESOLVED"

        envelope_payload: dict[str, Any] = {
            "reference": _proposal_reference(request.reference_id),
            "outcome": status,
            "units": str(units),
            "price": str(price),
            "filled_at": at.isoformat(),
            "broker_order_id": str(outcome.order_id),
            "lookup_sha256": response_sha256(payload),
        }
        if status in ("FILLED", "PARTIALLY_FILLED"):
            envelope_payload["broker_position_id"] = next(iter(position_ids))
        return self._signer.seal(envelope_payload)

    # Explicit alias for callers that use the domain term rather than endpoint name.
    seal_order_lookup = seal_open_lookup

    def seal_open_lookup_or_unresolved(
        self, payload: Mapping[str, Any], *, request: DemoOpenRequest,
        observed_at: datetime, accepted_order_id: int,
    ) -> Envelope:
        """Seal malformed or non-terminal lookup outcomes as UNRESOLVED, never as a fill.

        The accepted order id comes from the previously validated open response; response
        values cannot replace it.  The kill-switch is tripped when SD-074 resolves this
        envelope, and the caller must not retry the write.
        """
        try:
            return self.seal_open_lookup(payload, request=request, observed_at=observed_at,
                                         order_id=accepted_order_id)
        except BrokerAdapterError:
            at = _utc(observed_at, "observed_at")
            return self._signer.seal({
                "reference": _proposal_reference(request.reference_id),
                "outcome": "UNRESOLVED", "units": "0", "price": "0",
                "filled_at": at.isoformat(), "broker_order_id": str(accepted_order_id),
                "lookup_sha256": response_sha256(payload),
            })

    def seal_close_info(
        self, payload: Mapping[str, Any], *, request: DemoCloseRequest,
        acceptance: CloseAcceptance, observed_at: datetime, planned_bid: Decimal,
    ) -> Envelope:
        """Seal close evidence conservatively.

        The documented close-info response proves a closed-unit count but has no execution
        price.  A terminal no-fill can be reconciled as NOT_FILLED; any reported close stays
        UNRESOLVED until a price-bearing, validated execution record is available.
        """
        at = _utc(observed_at, "observed_at")
        if acceptance.position_id != request.position_id:
            raise BrokerAdapterError("close acceptance is not bound to the requested position")
        try:
            outcome = parse_close_info(payload, acceptance=acceptance)
        except (EtoroDemoOrderError, TypeError, ValueError) as exc:
            raise BrokerAdapterError(str(exc)) from None
        if outcome.terminal and outcome.status in ("REJECTED", "CANCELED", "EXPIRED") \
                and outcome.closed_units == 0:
            status, units, price = "NOT_FILLED", Decimal("0"), Decimal("0")
        else:
            # planned_bid is accepted only as a shape-checked diagnostic; it is not a fill price.
            if not planned_bid.is_finite() or planned_bid <= 0:
                raise BrokerAdapterError("planned bid must be positive and finite")
            status, units, price = "UNRESOLVED", Decimal("0"), Decimal("0")
        return self._signer.seal({
            "reference": _proposal_reference(request.reference_id),
            "outcome": status, "units": str(units), "price": str(price),
            "filled_at": at.isoformat(), "broker_order_id": str(acceptance.order_id),
            "broker_position_id": str(request.position_id),
            "lookup_sha256": response_sha256(payload),
        })

    def seal_simulated_close(
        self, payload: Mapping[str, Any], *, request: DemoCloseRequest,
        acceptance: CloseAcceptance, observed_at: datetime, fill_price: Decimal,
    ) -> Envelope:
        """Seal a deterministic simulator close; this is never broker evidence."""
        at = _utc(observed_at, "observed_at")
        if acceptance.position_id != request.position_id:
            raise BrokerAdapterError("close acceptance is not bound to the requested position")
        try:
            outcome = parse_close_info(payload, acceptance=acceptance)
        except (EtoroDemoOrderError, TypeError, ValueError) as exc:
            raise BrokerAdapterError(str(exc)) from None
        if (not outcome.terminal or outcome.status != "FILLED" or outcome.closed_units <= 0
                or (request.units_to_deduct is not None
                    and outcome.closed_units != request.units_to_deduct)
                or not fill_price.is_finite() or fill_price <= 0):
            raise BrokerAdapterError("simulated close outcome is not a valid full-price fill")
        return self._signer.seal({
            "reference": _proposal_reference(request.reference_id),
            "outcome": "FILLED", "units": str(outcome.closed_units),
            "price": str(fill_price), "filled_at": at.isoformat(),
            "broker_order_id": str(acceptance.order_id),
            "broker_position_id": str(acceptance.position_id),
            "lookup_sha256": response_sha256(payload),
        })
