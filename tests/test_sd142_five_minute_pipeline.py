from datetime import date, timedelta
from decimal import Decimal

import pytest

from sidedeck.application.sd068_track_scheduler import session_for
from sidedeck.application.sd142_five_minute_pipeline import (
    FiveMinuteDataError, coverage_report, ingest_provider_fixture,
    validate_five_minute_session,
)
from sidedeck.application.sd074_trusted_inputs import SourceSigner, TrustedSource

_SOURCE_KEY = b"five-minute-fixture-source-key-32-bytes-long"


def validate(rows, *, day, ingested_at):
    signer = SourceSigner(TrustedSource("fixture:test", "research_pipeline", _SOURCE_KEY),
                          clock=lambda: ingested_at)
    return validate_five_minute_session(
        rows, symbol="MSFT", instrument_id=1004, session_day=day,
        ingested_at=ingested_at, signer=signer,
    )


def rows_for(day: date):
    session = session_for(day)
    assert session is not None
    evidence_time = (session.open_utc - timedelta(days=1)).isoformat()
    rows = []
    stamp = session.open_utc
    while stamp + timedelta(minutes=5) <= session.close_utc:
        row = {"start": stamp.isoformat(), "bid_open": "100", "bid_high": "101",
               "bid_low": "99", "bid_close": "100.5", "ask_open": "100.1",
               "ask_high": "101.1", "ask_low": "99.1", "ask_close": "100.6",
               "volume": "1000", "source_id": "fixture:test", "source_hash": "a" * 64,
               "adjustment_basis": "RAW", "corporate_actions_asof": evidence_time,
               "mapping_status": "VERIFIED", "mapping_asof": evidence_time,
               "entitlement_status": "VERIFIED", "mapped_symbol": "MSFT",
               "mapped_instrument_id": "1004"}
        rows.append(row)
        stamp += timedelta(minutes=5)
    return rows, session


@pytest.mark.parametrize("day,expected_count,early", [
    (date(2026, 10, 26), 78, False),  # after DST fallback
    (date(2026, 11, 27), 42, True),   # Thanksgiving Friday early close
    (date(2026, 3, 9), 78, False),    # after DST spring transition
])
def test_complete_session_uses_exchange_calendar_and_dst(day, expected_count, early):
    rows, session = rows_for(day)
    bundle = validate(rows, day=day, ingested_at=session.close_utc + timedelta(minutes=1))
    assert len(bundle.bars) == expected_count
    assert bundle.report["early_close"] is early
    assert bundle.report["strategy_admission_eligible"] is False
    assert bundle.bars[0].open == Decimal("100.05")
    assert len(bundle.report["data_version_sha256"]) == 64
    assert bundle.provenance_envelope.source_id == "fixture:test"
    assert len(bundle.provenance_envelope.mac) == 64


@pytest.mark.parametrize("mutation,match", [
    (lambda rows: rows.pop(30), "missing bars"),
    (lambda rows: rows.__setitem__(1, dict(rows[0])), "duplicate"),
    (lambda rows: rows[0].update(ask_open="99.9", ask_low="98.9"), "bid exceeds ask"),
    (lambda rows: rows[0].update(entitlement_status="UNVERIFIED"), "entitlement"),
    (lambda rows: rows[0].update(adjustment_basis=""), "provenance"),
    (lambda rows: rows[0].update(mapped_instrument_id="9999"), "mapping does not match"),
    (lambda rows: rows[0].update(source_hash="not-a-hash"), "SHA-256"),
])
def test_bundle_rejects_gaps_duplicates_spread_and_unsupported_provenance(mutation, match):
    day = date(2026, 10, 26)
    rows, session = rows_for(day)
    mutation(rows)
    with pytest.raises(FiveMinuteDataError, match=match):
        validate(rows, day=day, ingested_at=session.close_utc + timedelta(minutes=1))


def test_bundle_rejects_stale_ingestion_and_naive_bar_time():
    day = date(2026, 10, 26)
    rows, session = rows_for(day)
    with pytest.raises(FiveMinuteDataError, match="stale"):
        validate(rows, day=day, ingested_at=session.close_utc + timedelta(minutes=5))
    rows[0]["start"] = "2026-10-26T09:30:00"
    with pytest.raises(FiveMinuteDataError, match="timezone"):
        validate(rows, day=day, ingested_at=session.close_utc + timedelta(minutes=1))


def test_coverage_report_keeps_research_only_status():
    day = date(2026, 10, 26)
    rows, session = rows_for(day)
    bundle = validate(rows, day=day, ingested_at=session.close_utc + timedelta(minutes=1))
    report = coverage_report([bundle])
    assert report["session_count"] == 1
    assert report["strategy_admission_eligible"] is False


def test_provider_fixture_adapter_is_pluggable_and_provenance_sealed():
    day = date(2026, 10, 26)
    rows, session = rows_for(day)

    class FixtureProvider:
        source_id = "fixture:test"

        def normalize(self, payload, *, symbol, instrument_id):
            assert symbol == "MSFT" and instrument_id == 1004
            return payload

    ingested_at = session.close_utc + timedelta(minutes=1)
    signer = SourceSigner(TrustedSource("fixture:test", "research_pipeline", _SOURCE_KEY),
                          clock=lambda: ingested_at)
    bundle = ingest_provider_fixture(
        FixtureProvider(), rows, symbol="MSFT", instrument_id=1004,
        session_day=day, ingested_at=ingested_at, signer=signer,
    )
    assert bundle.provenance_envelope.payload["data_version_sha256"] == \
        bundle.report["data_version_sha256"]

    with pytest.raises(FiveMinuteDataError, match="identities differ"):
        ingest_provider_fixture(
            FixtureProvider(), rows, symbol="MSFT", instrument_id=1004,
            session_day=day, ingested_at=ingested_at,
            signer=SourceSigner(TrustedSource("other:source", "research_pipeline", _SOURCE_KEY)),
        )
