from sidedeck.application.saxo_shortlist_precheck import SHORTLIST, identity_valid
from sidedeck.infrastructure.saxo_account_scope import SaxoAccountScope
from sidedeck.infrastructure.saxo_precheck import precheck_payload


def test_shortlist_uics_from_user_broker_output():
    assert SHORTLIST == {"SOFI": 23241352, "PLTR": 46019839, "INTC": 247}
    scope = SaxoAccountScope("22866064", "example", "client")
    for uic in SHORTLIST.values():
        payload = precheck_payload(scope, uic=uic)
        assert payload["Uic"] == uic
        assert payload["Amount"] == 1
        assert payload["AssetType"] == "Stock"


def test_requires_exact_symbol_currency_and_account():
    detail = {"Uic": 247, "Symbol": "INTC:xnas", "AssetType": "Stock",
              "CurrencyCode": "USD", "TradingStatus": "Tradable",
              "TradableOn": ["accountkey"]}
    assert identity_valid(detail, "INTC", 247, "accountkey")
    assert not identity_valid(detail, "INTC", 247, "other")
    assert not identity_valid({**detail, "Symbol": "INTC:xmil"}, "INTC", 247, "accountkey")
    assert not identity_valid({**detail, "CurrencyCode": "EUR"}, "INTC", 247, "accountkey")
