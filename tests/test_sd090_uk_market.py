from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from sidedeck.application.sd014_strategy_engine import StrategyBar
from sidedeck.application.sd065_market_universe import (
    InstrumentRecord,
    MarketUniverseRegistry,
    TickerInterval,
    isin_is_valid,
)
from sidedeck.application.sd090_uk_market import (
    LISTING_COLUMNS,
    MEMBERSHIP_COLUMNS,
    UK_CANDIDATE_WATCHLIST,
    QuoteInput,
    SeriesInput,
    UkMarketError,
    apply_index_memberships,
    candidate_identity_check,
    normalize_quote,
    normalize_series,
    normalize_unit_label,
    parse_uk_listings,
    to_major_unit,
    validate_tidm,
)
from sidedeck.application.sd096_uk_acceptance import fixture_isin

NOW = datetime(2026, 10, 23, 6, 30, tzinfo=UTC)
PROV = "fixture: hand-written test data, not market data"
LICENCE = "test-only synthetic rows"


def _record(unit: str = "GBX", isin: str | None = None) -> InstrumentRecord:
    return InstrumentRecord(
        canonical_id=f"UK:{isin or fixture_isin(1)}", name="Synthetic", country="GB",
        asset_type="COMMON_STOCK", currency="GBP",
        tickers=(TickerInterval("SYA", "LSE", date(2020, 1, 2)),), history_basis="POINT_IN_TIME",
        provenance=PROV, listing_date=date(2020, 1, 2), isin=isin or fixture_isin(1),
        quote_unit=unit,
    )


def _bars(*closes: str) -> tuple[StrategyBar, ...]:
    days = (date(2026, 10, 19), date(2026, 10, 20), date(2026, 10, 21), date(2026, 10, 22))
    return tuple(StrategyBar(d, Decimal(c), Decimal(c), Decimal(c), Decimal(c), Decimal(1000))
                 for d, c in zip(days, closes))


def _series(unit_label: str, *closes: str, basis: str = "SYNTHETIC_FIXTURE") -> SeriesInput:
    return SeriesInput(_record().canonical_id, "TEST", unit_label, basis, PROV,
                       datetime(2026, 10, 22, 18, tzinfo=UTC), _bars(*closes))


def test_unit_labels_are_case_sensitive_and_ambiguity_refused() -> None:
    assert normalize_unit_label("GBp") == "GBX"
    assert normalize_unit_label("GBX") == "GBX"
    assert normalize_unit_label("GBP") == "GBP"
    for bad in ("gbp", "Gbp", "GBX ", "pence", "", "GBp."):
        with pytest.raises(UkMarketError, match="UNKNOWN_OR_AMBIGUOUS_UNIT"):
            normalize_unit_label(bad)
    assert to_major_unit(Decimal("1234.5"), "GBX") == Decimal("12.345")
    assert to_major_unit(Decimal("12.345"), "GBP") == Decimal("12.345")


def test_series_normalized_from_pence_to_pounds_exactly() -> None:
    norm = normalize_series(_series("GBp", "1250", "1262.5", "1240", "1251"), _record(), NOW)
    assert norm.source_unit == "GBX" and norm.price_unit == "GBP" and norm.divisor == 100
    assert [b.close for b in norm.bars] == [Decimal("12.5"), Decimal("12.625"), Decimal("12.4"),
                                             Decimal("12.51")]
    assert norm.bars[0].volume == Decimal(1000)  # volume is never rescaled
    pounds = normalize_series(_series("GBP", "12.50", "12.6", "12.4", "12.51"), _record("GBP"),
                              NOW)
    assert pounds.divisor == 1 and pounds.bars[-1].close == Decimal("12.51")


def test_series_failures_are_closed_with_reasons() -> None:
    with pytest.raises(UkMarketError, match="SUSPECTED_UNIT_FLIP:2026-10-21"):
        normalize_series(_series("GBX", "1250", "1260", "12.55", "12.6"), _record(), NOW)
    with pytest.raises(UkMarketError, match="UNIT_CURRENCY_MISMATCH"):
        normalize_series(_series("USD", "1", "1", "1", "1"), _record(), NOW)
    with pytest.raises(UkMarketError, match="UNKNOWN_DATA_BASIS"):
        normalize_series(_series("GBX", "1", "1", "1", "1", basis="LIVE"), _record(), NOW)
    with pytest.raises(UkMarketError, match="FUTURE_RETRIEVAL_TIME"):
        normalize_series(_series("GBX", "1", "1", "1", "1"), _record(),
                         datetime(2026, 10, 22, 12, tzinfo=UTC))
    other = _record(isin=fixture_isin(2))
    with pytest.raises(UkMarketError, match="INSTRUMENT_MISMATCH"):
        normalize_series(_series("GBX", "1", "1", "1", "1"), other, NOW)
    late = SeriesInput(_record().canonical_id, "TEST", "GBX", "SYNTHETIC_FIXTURE", PROV,
                       datetime(2026, 10, 21, 18, tzinfo=UTC), _bars("1", "1", "1", "1"))
    with pytest.raises(UkMarketError, match="BAR_NOT_COMPLETE_AT_RETRIEVAL"):
        normalize_series(late, _record(), NOW)


def test_quotes_normalized_and_spread_is_unit_invariant() -> None:
    rec = _record()
    pence = normalize_quote(QuoteInput(rec.canonical_id, "T", "GBp", Decimal("999.5"),
                                       Decimal("1000.5"), NOW - timedelta(seconds=5),
                                       "SYNTHETIC_FIXTURE", PROV), rec, NOW,
                            max_age=timedelta(minutes=1))
    assert (pence.bid, pence.ask, pence.mid) == (Decimal("9.995"), Decimal("10.005"),
                                                 Decimal("10"))
    assert pence.spread_bps == Decimal(10)
    for bid, ask, at, reason in (
        (Decimal(10), Decimal(9), NOW, "CROSSED_QUOTE"),
        (Decimal(9), Decimal(10), NOW - timedelta(minutes=2), "STALE_QUOTE"),
        (Decimal(9), Decimal(10), NOW + timedelta(seconds=1), "FUTURE_QUOTE"),
        (Decimal(0), Decimal(10), NOW, "NON_POSITIVE_QUOTE"),
    ):
        with pytest.raises(UkMarketError, match=reason):
            normalize_quote(QuoteInput(rec.canonical_id, "T", "GBX", bid, ask, at,
                                       "SYNTHETIC_FIXTURE", PROV), rec, NOW,
                            max_age=timedelta(minutes=1))


def test_tidm_validation_refuses_vendor_symbols() -> None:
    for ok in ("BP.", "BT.A", "SHEL", "HSBA", "AZN", "ULVR", "III"):
        assert validate_tidm(ok) == ok
    for bad, reason in (("BP.L", "VENDOR"), ("AZN.LON", "VENDOR"), ("BARC LN", "VENDOR"),
                        ("LON:BP", "VENDOR"), ("shel", "INVALID"), ("TOOLONG", "INVALID"),
                        (" BP", "INVALID")):
        with pytest.raises(UkMarketError, match=reason):
            validate_tidm(bad)


def _csv(*rows: tuple[str, ...], header: tuple[str, ...] = LISTING_COLUMNS) -> str:
    return "\n".join([",".join(header), *(",".join(r) for r in rows)]) + "\n"


def test_listing_parser_merges_ticker_changes_and_rejects_guesses() -> None:
    a, b = fixture_isin(30), fixture_isin(31)
    text = _csv(
        ("OLDA", a, "Synthetic A", "ORDINARY_SHARE", "GBX", "GBP", "2015-03-02", "",
         "2015-03-02", "2024-05-31", "src", "2026-10-22"),
        ("NEWA", a, "Synthetic A", "ORDINARY_SHARE", "GBX", "GBP", "2015-03-02", "",
         "2024-06-03", "", "src", "2026-10-22"),
        ("SYB", b, "Synthetic B", "ORDINARY_SHARE", "GBX", "GBP", "2015-03-02", "", "", "",
         "src", "2026-10-22"),
        ("SYB", b, "Synthetic B renamed", "ORDINARY_SHARE", "GBX", "GBP", "2015-03-02", "", "",
         "", "src", "2026-10-22"),
        ("SYT", fixture_isin(32), "Trust", "INVESTMENT_TRUST", "GBX", "GBP", "", "", "", "",
         "src", "2026-10-22"),
        ("SYU", fixture_isin(33), "Unknown", "STAPLED_UNIT", "GBX", "GBP", "", "", "", "",
         "src", "2026-10-22"),
        ("SYM", "", "No ISIN", "ORDINARY_SHARE", "GBX", "GBP", "", "", "", "", "src",
         "2026-10-22"),
        ("SYN", "GB00BH4HKS38", "Bad ISIN", "ORDINARY_SHARE", "GBX", "GBP", "", "", "", "",
         "src", "2026-10-22"),
        ("SYP.L", fixture_isin(34), "Vendor", "ORDINARY_SHARE", "GBX", "GBP", "", "", "", "",
         "src", "2026-10-22"),
        ("SYQ", fixture_isin(35), "Ambiguous unit", "ORDINARY_SHARE", "gbp", "GBP", "", "", "",
         "", "src", "2026-10-22"),
    )
    report = parse_uk_listings(text, licence_note=LICENCE)
    reasons = dict(report.rejected)
    assert [r.canonical_id for r in report.records] == [f"UK:{a}"]
    rec = report.records[0]
    assert rec.ticker_on(date(2020, 1, 2)).ticker == "OLDA"  # type: ignore[union-attr]
    assert rec.ticker_on(date(2026, 10, 22)).ticker == "NEWA"  # type: ignore[union-attr]
    assert rec.quote_unit == "GBX" and rec.currency == "GBP" and rec.isin == a
    assert reasons[b] == "CONFLICTING_ROWS_FOR_ISIN"
    assert reasons[fixture_isin(32)] == "UNSUPPORTED_SECURITY_TYPE:INVESTMENT_TRUST"
    assert reasons[fixture_isin(33)] == "UNKNOWN_SECURITY_TYPE:STAPLED_UNIT"
    assert reasons["SYM"] == "MISSING_ISIN"
    assert reasons["GB00BH4HKS38"] == "INVALID_ISIN"
    assert reasons[fixture_isin(34)] == "VENDOR_SYMBOL_NOT_TIDM"
    assert reasons[fixture_isin(35)].startswith("UNKNOWN_OR_AMBIGUOUS_UNIT")
    with pytest.raises(UkMarketError, match="licence"):
        parse_uk_listings(text, licence_note=" ")
    with pytest.raises(UkMarketError, match="unexpected header"):
        parse_uk_listings("tidm,isin\nA,B\n", licence_note=LICENCE)


def test_snapshot_listing_and_membership_are_never_backdated() -> None:
    isin = fixture_isin(40)
    report = parse_uk_listings(_csv(
        ("SYS", isin, "Snapshot Co", "ORDINARY_SHARE", "GBX", "GBP", "", "", "", "", "src",
         "2026-10-22"),
    ), licence_note=LICENCE)
    rec = report.records[0]
    assert rec.history_basis == "SNAPSHOT" and rec.snapshot_date == date(2026, 10, 22)
    membership = _csv(("FTSE100", isin, "2026-10-22", "", "SNAPSHOT", "constituents list"),
                      header=MEMBERSHIP_COLUMNS)
    records, rejected = apply_index_memberships((rec,), membership, licence_note=LICENCE,
                                                 snapshot_date=date(2026, 10, 22))
    assert rejected == ()
    reg = MarketUniverseRegistry(1, NOW, "t", records)
    assert reg.universe_as_of(date(2026, 10, 22), markets=("UK",), index_id="FTSE100").members
    old = reg.universe_as_of(date(2025, 1, 2), markets=("UK",), index_id="FTSE100")
    assert old.members == () and old.survivorship_risk
    bad = _csv(("FTSE100", isin, "2020-01-02", "2026-01-02", "SNAPSHOT", "s"),
               ("FTSE350X", isin, "2020-01-02", "", "POINT_IN_TIME", "s"),
               ("FTSE250", fixture_isin(41), "2020-01-02", "", "POINT_IN_TIME", "s"),
               ("FTSE250", isin, "2020-01-02", "2019-01-02", "POINT_IN_TIME", "s"),
               header=MEMBERSHIP_COLUMNS)
    _, rejected = apply_index_memberships((rec,), bad, licence_note=LICENCE,
                                          snapshot_date=date(2026, 10, 22))
    assert [r for _, r in rejected] == ["SNAPSHOT_MEMBERSHIP_CANNOT_HAVE_END", "UNKNOWN_INDEX",
                                        "UNKNOWN_ISIN", "END_BEFORE_START"]


def test_candidate_watchlist_is_unverified_until_sourced() -> None:
    assert {c.proposed_tidm for c in UK_CANDIDATE_WATCHLIST} == {"BP.", "SHEL", "HSBA", "AZN",
                                                                "ULVR"}
    assert all(c.identity_status == "UNVERIFIED_PENDING_SOURCE" for c in UK_CANDIDATE_WATCHLIST)
    assert all(isin_is_valid(c.expected_isin) for c in UK_CANDIDATE_WATCHLIST)
    shell = next(c for c in UK_CANDIDATE_WATCHLIST if c.proposed_tidm == "SHEL")
    assert candidate_identity_check(shell, (), date(2026, 10, 22)) == ("NO_SOURCED_RECORD", None)
    sourced = InstrumentRecord(
        canonical_id="UK:X", name="x", country="GB", asset_type="COMMON_STOCK", currency="GBP",
        tickers=(TickerInterval("SHEL", "LSE", date(2022, 1, 31)),), history_basis="SNAPSHOT",
        provenance=PROV, snapshot_date=date(2026, 10, 22), isin=fixture_isin(50),
        quote_unit="GBX",
    )
    status, rec = candidate_identity_check(shell, (sourced,), date(2026, 10, 22))
    assert status == "ISIN_DIFFERS_FROM_EXPECTED_REVIEW_REQUIRED" and rec is sourced


def test_review_h1_snapshot_membership_cannot_be_backdated_and_is_deduplicated() -> None:
    isin = fixture_isin(42)
    rec = parse_uk_listings(_csv(
        ("SYZ", isin, "Z", "ORDINARY_SHARE", "GBX", "GBP", "2010-01-04", "", "", "", "src",
         "2026-10-22"),
    ), licence_note=LICENCE).records[0]
    backdated = _csv(("FTSE100", isin, "2000-01-01", "", "SNAPSHOT", "list"),
                     header=MEMBERSHIP_COLUMNS)
    out, rejected = apply_index_memberships((rec,), backdated, licence_note=LICENCE,
                                            snapshot_date=date(2026, 10, 22))
    assert rejected == ((isin, "SNAPSHOT_MEMBERSHIP_BACKDATED"),) and out[0].memberships == ()
    pit = _csv(("FTSE250", isin, "2015-03-23", "2019-06-21", "POINT_IN_TIME", "review 2015-03"),
               header=MEMBERSHIP_COLUMNS)
    once, _ = apply_index_memberships((rec,), pit, licence_note=LICENCE,
                                      snapshot_date=date(2026, 10, 22))
    twice, _ = apply_index_memberships(once, pit, licence_note=LICENCE,
                                       snapshot_date=date(2026, 10, 22))
    assert len(twice[0].memberships) == 1


def test_review_h2_mid_session_bar_is_not_a_close() -> None:
    mid = SeriesInput(_record().canonical_id, "TEST", "GBX", "SYNTHETIC_FIXTURE", PROV,
                      datetime(2026, 10, 22, 9, tzinfo=UTC), _bars("1", "1", "1", "1"))
    with pytest.raises(UkMarketError, match="BAR_NOT_COMPLETE_AT_RETRIEVAL:2026-10-22"):
        normalize_series(mid, _record(), NOW)
    dup = SeriesInput(_record().canonical_id, "TEST", "GBX", "SYNTHETIC_FIXTURE", PROV,
                      datetime(2026, 10, 22, 18, tzinfo=UTC), _bars("1", "1") + _bars("1"))
    with pytest.raises(UkMarketError, match="DUPLICATE_BAR"):
        normalize_series(dup, _record(), NOW)


def test_review_l1_short_rows_are_rejected_not_crashing() -> None:
    text = ",".join(LISTING_COLUMNS) + chr(10) + "SYA,ZZ" + chr(10)
    assert parse_uk_listings(text, licence_note=LICENCE).rejected == (("ZZ", "MALFORMED_ROW"),)
