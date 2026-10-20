"""Synthetic Saxo SIM gateway for offline tests (no network, no credentials).

It replaces only the HTTP opener inside ``sidedeck.infrastructure.saxo_sim``, so
the real ``SaxoSimClient`` (SIM base URL, path allowlist, GET-only, no
redirects), ``verified_scope`` and the evidence collectors all run unchanged.
The token value is a dummy string that never leaves the test process.
"""
from __future__ import annotations

import json
import os
from contextlib import ExitStack, contextmanager
from datetime import datetime
from typing import Any, Iterator
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from sidedeck.application import saxo_sim_evidence
from sidedeck.application.saxo_sim_evidence import collect_account_evidence
from sidedeck.application.saxo_sim_reconciliation import open_sim_books, reconcile_sim_account
from sidedeck.infrastructure.saxo_account_scope import verified_scope
from sidedeck.infrastructure.saxo_sim import SIM_BASE, SaxoSimClient
from sidedeck.infrastructure.saxo_sim_journal import SimJournalStore

ACCOUNT = "22866064"
SOFI = 23241352


class _Response:
    status = 200

    def __init__(self, body: Any) -> None:
        self._raw = json.dumps(body).encode("utf-8")

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *args: Any) -> bool:
        return False

    def read(self, limit: int) -> bytes:
        return self._raw[:limit]


class SyntheticGateway:
    """Serves synthetic Saxo SIM GET responses; anything else fails the test."""

    def __init__(self, account_id: str = ACCOUNT, *, client_key: str = "synthetic-client",
                 account_key: str = "synthetic-account-key",
                 positions: list[tuple[int, Any]] | None = None, cash: Any = 10000,
                 activity: list[dict[str, Any]] | None = None,
                 prices: dict[str, dict[str, Any]] | None = None) -> None:
        self.account_id = account_id
        self.client_key = client_key
        self.account_key = account_key
        self.positions = positions or []
        self.cash = cash
        self.activity = activity or []
        self.prices = prices or {}
        self.positions_response: dict[str, Any] | None = None
        self.balance_response: dict[str, Any] | None = None
        self.urls: list[str] = []

    def opener(self, *handlers: Any) -> "SyntheticGateway":
        return self

    def open(self, request: Any, timeout: float) -> _Response:
        assert request.get_method() == "GET", "the synthetic gateway only serves GET"
        url = request.full_url
        assert url.startswith(SIM_BASE + "/"), "only the Saxo SIM base URL is allowed"
        self.urls.append(url)
        parts = urlsplit(url[len(SIM_BASE):])
        return _Response(self.respond(parts.path, parse_qs(parts.query)))

    def respond(self, path: str, query: dict[str, list[str]]) -> Any:
        if path == "/port/v1/users/me":
            return {"ClientKey": self.client_key}
        if path == "/port/v1/accounts/me":
            return {"Data": [{"AccountId": self.account_id, "AccountKey": self.account_key,
                              "Active": True}]}
        if path == "/port/v1/positions":
            return self.positions_response or {"Data": [
                {"PositionBase": {"AccountId": self.account_id, "Uic": uic, "Amount": amount}}
                for uic, amount in self.positions]}
        if path == "/port/v1/balances":
            return self.balance_response or {"Currency": "EUR", "CashBalance": self.cash}
        if path == "/cs/v1/audit/orderactivities":
            return {"Data": self.activity, "__count": len(self.activity)}
        if path == "/trade/v1/infoprices":
            return self.prices[query["AssetType"][0]]
        raise AssertionError(f"unexpected synthetic Saxo path {path}")


def fill_row(order_key: str, amount: Any, *, execution_id: str | None = None,
             account_id: str = ACCOUNT, status: str = "FinalFill", side: str = "Buy") -> dict[str, Any]:
    return {"AccountId": account_id, "OrderId": "broker-" + order_key, "ExternalReference": order_key,
            "Status": status, "BuySell": side, "Uic": SOFI, "FillAmount": amount,
            "ExecutionId": execution_id or f"exec-{order_key}-{amount}", "ExecutionPrice": 40}


@contextmanager
def clock(at: datetime) -> Iterator[None]:
    with mock.patch.object(saxo_sim_evidence, "utcnow", lambda: at):
        yield


@contextmanager
def synthetic_gateway(gateway: SyntheticGateway, at: datetime | None = None) -> Iterator[SyntheticGateway]:
    with ExitStack() as stack:
        stack.enter_context(mock.patch.dict(os.environ,
                                            {"SAXO_SIM_ACCESS_TOKEN": "synthetic-offline-token"}))
        stack.enter_context(mock.patch("sidedeck.infrastructure.saxo_sim.build_opener",
                                       gateway.opener))
        if at is not None:
            stack.enter_context(clock(at))
        yield gateway


def authenticated(gateway: SyntheticGateway) -> tuple[SaxoSimClient, Any]:
    """Must be called inside synthetic_gateway(); returns the real client and verified scope."""
    client = SaxoSimClient()
    return client, verified_scope(client, gateway.account_id)


def read_evidence(gateway: SyntheticGateway, at: datetime):
    with synthetic_gateway(gateway, at):
        client, scope = authenticated(gateway)
        return collect_account_evidence(client, scope)


def open_books(db_path: str, at: datetime, gateway: SyntheticGateway | None = None) -> SimJournalStore:
    store = SimJournalStore(db_path)
    evidence = read_evidence(gateway or SyntheticGateway(), at)
    with clock(at):
        open_sim_books(store, evidence, approval_ref="owner-decision-2026-10-20")
    return store


def reconcile(store: SimJournalStore, gateway: SyntheticGateway, at: datetime):
    evidence = read_evidence(gateway, at)
    with clock(at):
        return reconcile_sim_account(store, evidence)


def set_frozen(store: SimJournalStore, books: tuple[str, ...], *, scope: str, at: datetime) -> None:
    """Test-only state setup via the private storage primitive (bypasses evidence on purpose)."""
    with store.transaction() as db:
        store._freeze(db, books, scope=scope, reason="test state", at=at)


def set_open(store: SimJournalStore, books: tuple[str, ...], at: datetime) -> None:
    """Test-only state setup; production release goes through release_freeze()."""
    with store.transaction() as db:
        store._release(db, books, released_by="test-setup", report_id="test",
                       attestation_sha256="0" * 64, at=at)
