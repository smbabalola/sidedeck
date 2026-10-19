import sys
from decimal import Decimal

from sidedeck.application import paper_preflight
from sidedeck.infrastructure.alpaca_readonly import PaperAccount


class FakeClient:
    def __init__(self, orders):
        self.orders = orders

    def account(self):
        return PaperAccount("fake-account", "USD", Decimal("2000"), Decimal("2000"), "ACTIVE")

    def positions(self):
        return ()

    def open_order_count(self):
        return self.orders


def test_preflight_blocks_open_orders(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["paper_preflight", "--expected-account-id", "fake-account"])
    monkeypatch.setattr(paper_preflight, "make_paper_get", lambda binding: object())
    monkeypatch.setattr(paper_preflight, "AlpacaReadOnly", lambda binding, transport: FakeClient(1))
    assert paper_preflight.main() == 2
    assert "BLOCKED: outstanding paper orders" in capsys.readouterr().out


def test_preflight_identity_only_success_is_not_reconciliation(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["paper_preflight", "--expected-account-id", "fake-account"])
    monkeypatch.setattr(paper_preflight, "make_paper_get", lambda binding: object())
    monkeypatch.setattr(paper_preflight, "AlpacaReadOnly", lambda binding, transport: FakeClient(0))
    assert paper_preflight.main() == 0
    assert "NOT reconciled" in capsys.readouterr().out
