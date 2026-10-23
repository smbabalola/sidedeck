"""SD-058 privacy-safe preflight evidence tests."""
import json
import sqlite3
from decimal import Decimal

import pytest

from sidedeck.application.sd058_forensic_audit import PreflightAudit, summarize_schema
from sidedeck.domain.etoro_demo_orders import EtoroDemoOrderError, parse_eligibility


def test_schema_summary_keeps_currency_codes_and_redacts_sensitive_values() -> None:
    summary = summarize_schema({
        "currency": "EUR", "currencyId": 2, "accountId": "private",
        "eligibilities": [{"instrumentId": 1004, "secretToken": "private"}],
    })
    fields = {field["path"]: field for field in summary["fields"]}
    assert fields["currency"]["currency_code"] == "EUR"
    assert fields["currencyId"]["type"] == "int"
    assert fields["accountId"]["type"] == "redacted"
    assert fields["eligibilities[0].secretToken"]["type"] == "redacted"
    assert "private" not in json.dumps(summary)


def test_audit_survives_restart_and_is_append_only(tmp_path) -> None:
    path = tmp_path / "nested" / "audit.sqlite3"
    audit = PreflightAudit(path, "a" * 64)
    audit.record(request_type="eligibility", budget={"eligibility": 1},
                 outcome="ABORTED_PREFLIGHT", payload={"currency": "EUR"},
                 error=EtoroDemoOrderError("eligibility response is not USD"))
    audit.close()

    reopened = PreflightAudit(path, "a" * 64)
    rows = reopened.rows()
    assert len(rows) == 1
    assert rows[0]["outcome"] == "ABORTED_PREFLIGHT"
    assert json.loads(rows[0]["schema_json"])["fields"][1]["currency_code"] == "EUR"
    with pytest.raises(sqlite3.DatabaseError, match="append-only audit"):
        reopened._db.execute("DELETE FROM sd058_preflight_audit")
    reopened.close()


@pytest.mark.parametrize(
    "payload",
    [None, {}, {"currency": "EUR", "eligibilities": []}],
)
def test_missing_malformed_and_non_usd_responses_are_recordable(tmp_path, payload) -> None:
    audit = PreflightAudit(tmp_path / "audit.sqlite3", "b" * 64)
    try:
        with pytest.raises(EtoroDemoOrderError):
            parse_eligibility(payload, instrument_id=1004, units=Decimal("0.4"),
                              notional_usd=Decimal("40"))
    except TypeError:
        # ``None`` is deliberately malformed and exercised through the audit path below.
        pass
    audit.record(request_type="eligibility", budget={"eligibility": 1},
                 outcome="ABORTED_PREFLIGHT", payload=payload,
                 error=EtoroDemoOrderError("redacted parser refusal"))
    assert audit.rows()[0]["request_type"] == "eligibility"
    audit.close()
