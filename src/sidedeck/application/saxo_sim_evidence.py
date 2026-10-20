"""Sealed, read-only Saxo SIM evidence for reconciliation and Stage 2 checks.

Everything here is GET-only through ``SaxoSimClient`` (exact type, SIM base
URL, path allowlist, no redirects) with an account scope that
``verified_scope()`` derived from authenticated SIM responses. Each result is
sealed with a process-local key, so a hand-built, fixture-parsed or
previous-process object can never pass ``is_verified()``.

* ``collect_account_evidence`` -> complete positions, EUR cash balance and
  per-order fill totals for ONE account, bound to that account's verified keys.
* ``SaxoSimMarketEvidence`` -> SOFI quote and EUR/USD rate from SIM infoprices,
  and a verifier that accepts only snapshots this instance read itself.

Nothing in this module submits, amends or cancels an order, or touches the
research ledgers or Alpaca paper accounts. Tests make no live call: they drive
the real client against a synthetic HTTP opener.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import quote as url_quote

from sidedeck.application.saxo_execution_history import read_account_activity
from sidedeck.application.saxo_market_data import (
    EvidenceOrigin, ExecutionEvidence, FxSnapshot, collect_execution_evidence,
)
from sidedeck.domain.contracts import MarketSnapshot, PriceType, Session
from sidedeck.domain.sim_accounting import SimAccountingError
from sidedeck.infrastructure.saxo_account_scope import SaxoAccountScope, scope_digest, scoped_get
from sidedeck.infrastructure.saxo_sim import EURUSD_UIC, SIM_BASE, SaxoSimClient

SOURCE = "saxo-sim-openapi"
MARKET_PROVIDER = "saxo-sim-infoprices"
MAX_EVIDENCE_AGE = timedelta(minutes=5)
MAX_CLOCK_SKEW = timedelta(seconds=5)
SOFI_UIC = 23241352
QUOTE_INSTRUMENTS = {"SOFI": SOFI_UIC}
INSTRUMENT_IDS = {SOFI_UIC: "US:SOFI"}
# Process-local key: only collect_account_evidence() in this process can seal.
_ACCOUNT_SEAL_KEY = secrets.token_bytes(32)


def utcnow() -> datetime:
    """Single clock for evidence, reconciliation and release decisions."""
    return datetime.now(timezone.utc)


class SimEvidenceError(SimAccountingError):
    """Broker evidence is missing, incomplete, unauthenticated or stale."""


def _require_gateway(client: object, scope: object) -> tuple[SaxoSimClient, SaxoAccountScope]:
    if type(client) is not SaxoSimClient or client.base_url != SIM_BASE:
        raise SimEvidenceError("evidence must be read through the Saxo SIM gateway client")
    if not isinstance(scope, SaxoAccountScope) or not scope.is_authenticated():
        raise SimEvidenceError("evidence needs an account scope verified from SIM responses")
    return client, scope


def _decimal(value: Any, what: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise SimEvidenceError(f"{what} missing")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise SimEvidenceError(f"{what} invalid") from exc
    if not result.is_finite():
        raise SimEvidenceError(f"{what} invalid")
    return result


def _timestamp(value: Any, what: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise SimEvidenceError(f"{what} missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SimEvidenceError(f"{what} invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SimEvidenceError(f"{what} must carry a timezone")
    return parsed.astimezone(timezone.utc)


def _require_fresh(observed: datetime, now: datetime, max_age: timedelta, what: str) -> None:
    age = now - observed
    if age < -MAX_CLOCK_SKEW:
        raise SimEvidenceError(f"{what} is future-dated")
    if age > max_age:
        raise SimEvidenceError(f"{what} is stale")


# --- account evidence ---------------------------------------------------------

def parse_positions(response: Any, account_id: str) -> dict[int, Decimal]:
    """Complete, account-scoped net positions keyed by Uic; partial pages fail closed."""
    rows = response.get("Data") if isinstance(response, dict) else None
    if not isinstance(rows, list):
        raise SimEvidenceError("positions response malformed")
    if response.get("__next") or (type(response.get("__count")) is int
                                   and response["__count"] != len(rows)):
        raise SimEvidenceError("positions response incomplete")
    totals: dict[int, Decimal] = {}
    for row in rows:
        base = row.get("PositionBase") if isinstance(row, dict) else None
        if not isinstance(base, dict) or base.get("AccountId") != account_id:
            raise SimEvidenceError("position does not belong to the SIM account")
        uic = base.get("Uic")
        if type(uic) is not int or uic <= 0:
            raise SimEvidenceError("position instrument missing")
        totals[uic] = totals.get(uic, Decimal("0")) + _decimal(base.get("Amount"), "position amount")
    return totals


def parse_cash_balance(response: Any) -> Decimal:
    """Account cash in EUR; anything else is missing evidence, never a match."""
    if not isinstance(response, dict) or response.get("Currency") != "EUR":
        raise SimEvidenceError("cash balance is not reported in the EUR account currency")
    return _decimal(response.get("CashBalance"), "cash balance")


def parse_fill_totals(rows: tuple[dict[str, Any], ...], account_id: str) -> dict[str, Decimal]:
    """Broker fill quantity per ExternalReference (SideDeck order key)."""
    totals: dict[str, Decimal] = {}
    seen: set[str] = set()
    for row in rows:
        if row.get("AccountId") != account_id:
            raise SimEvidenceError("order activity belongs to another account")
        if row.get("Status") not in ("Fill", "FinalFill"):
            continue
        reference = row.get("ExternalReference")
        if not isinstance(reference, str) or not reference:
            continue  # manual orders surface as unexplained position differences
        if row.get("BuySell") != "Buy":
            raise SimEvidenceError("sell fills are not supported for SideDeck orders")
        execution_id = row.get("ExecutionId") or row.get("LogId")
        if not isinstance(execution_id, str) or not execution_id or execution_id in seen:
            raise SimEvidenceError("missing or duplicate execution identity in order activity")
        seen.add(execution_id)
        amount = _decimal(row.get("FillAmount"), "fill amount")
        if amount <= 0:
            raise SimEvidenceError("fill amount invalid")
        totals[reference] = totals.get(reference, Decimal("0")) + amount
    return totals


@dataclass(frozen=True)
class SimAccountEvidence:
    """One complete read of one SIM account. Valid only if sealed in this process."""

    evidence_id: str
    source: str
    account_id: str
    scope_sha256: str
    observed_at: datetime
    positions: tuple[tuple[int, Decimal], ...]
    cash_balance_eur: Decimal
    order_fill_totals: tuple[tuple[str, Decimal], ...]
    response_sha256: str
    seal: str = field(default="", repr=False, compare=False)

    def _material(self) -> bytes:
        return json.dumps([
            self.evidence_id, self.source, self.account_id, self.scope_sha256,
            self.observed_at.isoformat(), [[uic, str(qty)] for uic, qty in self.positions],
            str(self.cash_balance_eur), [[key, str(qty)] for key, qty in self.order_fill_totals],
            self.response_sha256,
        ], separators=(",", ":")).encode("utf-8")

    def digest(self) -> str:
        return hashlib.sha256(self._material()).hexdigest()

    def is_verified(self) -> bool:
        if not self.seal:
            return False
        expected = hmac.new(_ACCOUNT_SEAL_KEY, self._material(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, self.seal)

    def positions_by_uic(self) -> dict[int, Decimal]:
        return dict(self.positions)

    def fill_totals(self) -> dict[str, Decimal]:
        return dict(self.order_fill_totals)

    def require_fresh(self, now: datetime, max_age: timedelta = MAX_EVIDENCE_AGE) -> None:
        _require_fresh(self.observed_at, now, max_age, "account evidence")


def require_verified(evidence: object) -> SimAccountEvidence:
    if not isinstance(evidence, SimAccountEvidence) or not evidence.is_verified():
        raise SimEvidenceError("broker evidence was not collected by the read-only SIM gateway")
    if evidence.source != SOURCE:
        raise SimEvidenceError("broker evidence source is not the Saxo SIM gateway")
    return evidence


def collect_account_evidence(client: SaxoSimClient, scope: SaxoAccountScope) -> SimAccountEvidence:
    """Read positions, EUR cash and order activity for one verified account (GET only)."""
    client, scope = _require_gateway(client, scope)
    # Freshness and freeze ordering use the start of the read window (the earliest moment).
    started = utcnow()
    positions_response = scoped_get(client, "positions", scope)
    balance_response = scoped_get(client, "balances", scope)
    try:
        activity = read_account_activity(client, scope)
    except ValueError as exc:
        raise SimEvidenceError(f"order activity incomplete: {exc}") from exc
    positions = parse_positions(positions_response, scope.account_id)
    cash = parse_cash_balance(balance_response)
    totals = parse_fill_totals(activity, scope.account_id)
    response_sha256 = hashlib.sha256(json.dumps(
        [positions_response, balance_response, list(activity)],
        sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()
    evidence = SimAccountEvidence(
        evidence_id=str(uuid.uuid4()), source=SOURCE, account_id=scope.account_id,
        scope_sha256=scope_digest(scope), observed_at=started,
        positions=tuple(sorted((uic, qty) for uic, qty in positions.items() if qty != 0)),
        cash_balance_eur=cash, order_fill_totals=tuple(sorted(totals.items())),
        response_sha256=response_sha256)
    seal = hmac.new(_ACCOUNT_SEAL_KEY, evidence._material(), hashlib.sha256).hexdigest()
    return replace(evidence, seal=seal)


# --- quote and FX evidence ------------------------------------------------------

class _Fetched:
    """Hands already-read snapshots to collect_execution_evidence at one cutoff."""

    def __init__(self, quote: MarketSnapshot, fx: FxSnapshot) -> None:
        self._quote, self._fx = quote, fx

    def quote(self, ticker: str, *, as_of: datetime) -> MarketSnapshot:
        return self._quote

    def fx(self, pair: str, *, as_of: datetime) -> FxSnapshot:
        return self._fx


class SaxoSimMarketEvidence:
    """SOFI and EUR/USD from Saxo SIM infoprices, bound to one verified account.

    Acts as both ``MarketDataProvider`` and ``MarketEvidenceVerifier``. ``verify``
    accepts only snapshots this instance read itself (instance-local MAC), with
    the authenticated-provider origin, while still fresh. Prices must be
    tradable and undelayed and, for the stock, in the open regular session.
    The quote price is the Ask: a buy executes there, so the spread is in it.
    """

    def __init__(self, client: SaxoSimClient, scope: SaxoAccountScope, *,
                 max_age: timedelta = timedelta(minutes=2)) -> None:
        self._client, self._scope = _require_gateway(client, scope)
        if not timedelta(0) < max_age <= timedelta(minutes=2):
            raise ValueError("market evidence max_age must be within two minutes")
        self._max_age = max_age
        self._key = secrets.token_bytes(32)
        self._observed: set[str] = set()
        self.account_id = scope.account_id
        self.bound_scope_sha256 = scope_digest(scope)

    def _mac(self, kind: str, material: str) -> str:
        return hmac.new(self._key, f"{kind}\n{material}".encode("utf-8"), hashlib.sha256).hexdigest()

    @staticmethod
    def _quote_material(snapshot: MarketSnapshot) -> str:
        return snapshot.model_dump_json()

    @staticmethod
    def _fx_material(snapshot: FxSnapshot) -> str:
        return json.dumps([snapshot.provider, snapshot.pair, str(snapshot.usd_per_eur),
                           snapshot.observed_at.isoformat(), snapshot.ingestion_at.isoformat(),
                           snapshot.quality], separators=(",", ":"))

    def _info_price(self, asset_type: str, uic: int) -> tuple[dict[str, Any], Decimal, Decimal,
                                                              datetime, datetime]:
        key = url_quote(self._scope.account_key, safe="")
        response = self._client.get(
            f"/trade/v1/infoprices?AccountKey={key}&AssetType={asset_type}&Uic={uic}")
        now = utcnow()
        if response.get("Uic") != uic or response.get("AssetType") != asset_type:
            raise SimEvidenceError("price response is for a different instrument")
        quote = response.get("Quote")
        if not isinstance(quote, dict):
            raise SimEvidenceError("price response has no quote")
        if quote.get("ErrorCode") not in (None, "None"):
            raise SimEvidenceError("broker reports the price as unavailable")
        if quote.get("DelayedByMinutes") != 0:
            raise SimEvidenceError("price is delayed")
        if quote.get("PriceTypeAsk") != "Tradable" or quote.get("PriceTypeBid") != "Tradable":
            raise SimEvidenceError("price is not tradable")
        bid = _decimal(quote.get("Bid"), "bid")
        ask = _decimal(quote.get("Ask"), "ask")
        if not Decimal("0") < bid <= ask:
            raise SimEvidenceError("bid/ask invalid")
        updated = _timestamp(response.get("LastUpdated"), "price timestamp")
        _require_fresh(updated, now, self._max_age, "price")
        # Within the allowed clock skew, never report a market time after ingestion.
        return response, bid, ask, min(updated, now), now

    def quote(self, ticker: str, *, as_of: datetime | None = None) -> MarketSnapshot:
        uic = QUOTE_INSTRUMENTS.get(ticker)
        if uic is None:
            raise SimEvidenceError("instrument is not approved for SIM quotes")
        response, _bid, ask, market_time, now = self._info_price("Stock", uic)
        if response["Quote"].get("MarketState") != "Open":
            raise SimEvidenceError("market is not in its regular session")
        if (response.get("DisplayAndFormat") or {}).get("Currency") != "USD":
            raise SimEvidenceError("quote currency is not USD")
        snapshot = MarketSnapshot(
            instrument_id=INSTRUMENT_IDS[uic], ticker=ticker, provider=MARKET_PROVIDER,
            price_type=PriceType.QUOTE, price=ask, market_timestamp=market_time,
            ingestion_timestamp=now, session=Session.REGULAR, quality="saxo-sim-tradable-ask")
        self._observed.add(self._mac("quote", self._quote_material(snapshot)))
        return snapshot

    def fx(self, pair: str, *, as_of: datetime | None = None) -> FxSnapshot:
        if pair != "EUR/USD":
            raise SimEvidenceError("only EUR/USD is approved")
        _response, bid, ask, market_time, now = self._info_price("FxSpot", EURUSD_UIC)
        snapshot = FxSnapshot(MARKET_PROVIDER, "EUR/USD", (bid + ask) / 2, market_time, now,
                              "saxo-sim-tradable-mid")
        self._observed.add(self._mac("fx", self._fx_material(snapshot)))
        return snapshot

    def verify(self, evidence: ExecutionEvidence) -> bool:
        if type(evidence) is not ExecutionEvidence:
            return False
        if (evidence.quote_origin is not EvidenceOrigin.AUTHENTICATED_PROVIDER
                or evidence.fx_origin is not EvidenceOrigin.AUTHENTICATED_PROVIDER):
            return False
        if (self._mac("quote", self._quote_material(evidence.quote)) not in self._observed
                or self._mac("fx", self._fx_material(evidence.fx)) not in self._observed):
            return False
        now = utcnow()
        return all(timedelta(0) <= now - stamp <= self._max_age
                   for stamp in (evidence.quote.ingestion_timestamp, evidence.fx.ingestion_at))

    def collect_sofi(self, *, fees_usd: Decimal = Decimal("0"),
                     fx_fee_usd: Decimal = Decimal("0")) -> ExecutionEvidence:
        """Read both legs, then bundle them at one cutoff and verify the bundle."""
        quote = self.quote("SOFI")
        fx = self.fx("EUR/USD")
        return collect_execution_evidence(
            _Fetched(quote, fx), ticker="SOFI", as_of=utcnow(), verifier=self,
            max_age=self._max_age, spread_usd=Decimal("0"), fees_usd=fees_usd,
            fx_fee_usd=fx_fee_usd, quote_origin=EvidenceOrigin.AUTHENTICATED_PROVIDER,
            fx_origin=EvidenceOrigin.AUTHENTICATED_PROVIDER)
