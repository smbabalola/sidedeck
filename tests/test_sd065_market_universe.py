from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from sidedeck.application.sd065_market_universe import (
    MARKETS,
    BrokerMapping,
    CorporateAction,
    IndexMembership,
    InstrumentRecord,
    MarketUniverseRegistry,
    SourceCoverage,
    TickerInterval,
    UniverseError,
    evaluate_eligibility,
    merge_snapshots,
    parse_nasdaq_symbol_directory,
)

NOW = datetime(2026, 10, 22, 12, tzinfo=UTC)
PROV = "fixture: hand-written test record, not market data"


def _cov(first: date, last: date, sessions: int) -> SourceCoverage:
    return SourceCoverage("FIXTURE_DAILY", "1D", first, last, sessions, PROV)


def _rec(cid: str, ticker: str, listing: date, **kw: object) -> InstrumentRecord:
    base = InstrumentRecord(
        canonical_id=cid, name=f"{ticker} Corp", country="US", asset_type="COMMON_STOCK",
        currency="USD", tickers=(TickerInterval(ticker, "NASDAQ", listing),),
        history_basis="POINT_IN_TIME", provenance=PROV, listing_date=listing,
    )
    return replace(base, **kw)  # type: ignore[arg-type]


def _registry(*records: InstrumentRecord) -> MarketUniverseRegistry:
    return MarketUniverseRegistry(1, NOW, "fixture", records)


def test_point_in_time_universe_excludes_unlisted_and_delisted() -> None:
    alive = _rec("US:AAA", "AAA", date(2010, 1, 4))
    late = _rec("US:BBB", "BBB", date(2024, 6, 3))
    dead = _rec("US:CCC", "CCC", date(2005, 1, 3), delisting_date=date(2020, 3, 2),
                tickers=(TickerInterval("CCC", "NASDAQ", date(2005, 1, 3), date(2020, 3, 2)),))
    reg = _registry(alive, late, dead)
    ids_2019 = [r.canonical_id for r in reg.universe_as_of(date(2019, 5, 1)).members]
    ids_2025 = [r.canonical_id for r in reg.universe_as_of(date(2025, 5, 1)).members]
    # A delisted name is in the 2019 universe (no survivorship bias) and not in 2025.
    assert ids_2019 == ["US:AAA", "US:CCC"]
    assert ids_2025 == ["US:AAA", "US:BBB"]


def test_index_membership_is_dated() -> None:
    member = _rec("US:AAA", "AAA", date(2010, 1, 4), memberships=(
        IndexMembership("SP500", date(2015, 1, 2), date(2021, 12, 17), PROV),
    ))
    reg = _registry(member)
    assert reg.universe_as_of(date(2018, 1, 2), index_id="SP500").members
    assert not reg.universe_as_of(date(2023, 1, 3), index_id="SP500").members
    assert not reg.universe_as_of(date(2012, 1, 3), index_id="SP500").members


def test_symbol_change_resolves_by_date_and_rejects_overlap() -> None:
    renamed = _rec("US:META", "FB", date(2012, 5, 18), tickers=(
        TickerInterval("FB", "NASDAQ", date(2012, 5, 18), date(2022, 6, 8)),
        TickerInterval("META", "NASDAQ", date(2022, 6, 9)),
    ), actions=(CorporateAction("SYMBOL_CHANGE", date(2022, 6, 9), "FB->META", PROV),))
    reg = _registry(renamed)
    assert reg.resolve("FB", date(2020, 1, 2)).canonical_id == "US:META"
    assert reg.resolve("META", date(2023, 1, 3)).canonical_id == "US:META"
    with pytest.raises(UniverseError):
        reg.resolve("FB", date(2023, 1, 3))
    overlapping = _rec("US:X", "X", date(2010, 1, 4), tickers=(
        TickerInterval("X", "NASDAQ", date(2010, 1, 4), date(2015, 1, 2)),
        TickerInterval("Y", "NASDAQ", date(2014, 1, 2)),
    ))
    with pytest.raises(UniverseError, match="overlap"):
        _registry(overlapping)


def test_duplicate_ticker_across_instruments_is_refused_but_reuse_after_gap_is_ok() -> None:
    a = _rec("US:OLD", "ABC", date(2000, 1, 3), delisting_date=date(2010, 1, 4),
             tickers=(TickerInterval("ABC", "NASDAQ", date(2000, 1, 3), date(2010, 1, 4)),))
    clash = _rec("US:NEW", "ABC", date(2009, 1, 2))
    with pytest.raises(UniverseError, match="at once"):
        _registry(a, clash)
    reused = _rec("US:NEW", "ABC", date(2015, 1, 2))
    reg = _registry(a, reused)
    assert reg.resolve("ABC", date(2005, 1, 3)).canonical_id == "US:OLD"
    assert reg.resolve("ABC", date(2020, 1, 2)).canonical_id == "US:NEW"


def test_ambiguous_ticker_across_exchanges_needs_exchange() -> None:
    a = _rec("US:A1", "DUP", date(2010, 1, 4))
    b = _rec("US:A2", "DUP", date(2010, 1, 4),
             tickers=(TickerInterval("DUP", "NYSE", date(2010, 1, 4)),))
    reg = _registry(a, b)
    with pytest.raises(UniverseError, match="ambiguous"):
        reg.resolve("DUP", date(2020, 1, 2))
    assert reg.resolve("DUP", date(2020, 1, 2), exchange="NYSE").canonical_id == "US:A2"


@pytest.mark.parametrize("bad", [
    {"asset_type": "CRYPTO"},
    {"name": "Bitcoin Trust BTC"},
    {"name": "iShares Ethereum Trust ETF"},
    {"name": "Grayscale (BTC) Mini"},
    {"tickers": (TickerInterval("BTC", "NYSE_ARCA", date(2010, 1, 4)),)},
    {"currency": "usd"},
    {"provenance": " "},
    {"history_basis": "GUESS"},
    {"listing_date": None},
    {"tickers": ()},
    {"tickers": (TickerInterval("ok", "NASDAQ", date(2010, 1, 4)),)},
    {"tickers": (TickerInterval("OK", "MOON", date(2010, 1, 4)),)},
    {"delisting_date": date(2001, 1, 2)},
    {"broker_mappings": (BrokerMapping("ETORO", "REAL", "1", NOW, "x", False),)},
    {"broker_mappings": (BrokerMapping("ETORO", "DEMO", "1", None, "", True),)},
    {"actions": (CorporateAction("MAGIC", date(2011, 1, 3), "", PROV),)},
])
def test_invalid_records_fail_closed(bad: dict[str, object]) -> None:
    with pytest.raises(UniverseError):
        _registry(_rec("US:ZZZ", "ZZZ", date(2010, 1, 4), **bad))


def test_eligibility_flags_are_independent() -> None:
    as_of = date(2026, 10, 21)
    cov = (_cov(date(2016, 1, 4), date(2026, 10, 20), 2700),)
    discovery_only = _rec("US:AAA", "AAA", date(2010, 1, 4), coverage=cov)
    report = evaluate_eligibility(discovery_only, as_of)
    assert report.discovery_eligible and report.strategy_eligible
    assert not report.flags["BROKER_MAPPED"] and not report.execution_eligible
    assert "NO_BROKER_MAPPING" in report.reasons

    unverified = replace(discovery_only, broker_mappings=(
        BrokerMapping("ETORO", "DEMO", "9", None, "", False),))
    assert not evaluate_eligibility(unverified, as_of).flags["BROKER_MAPPED"]

    mapped_not_exec = replace(discovery_only, broker_mappings=(
        BrokerMapping("ETORO", "DEMO", "9", NOW, "one-shot lookup", False),))
    r = evaluate_eligibility(mapped_not_exec, as_of)
    assert r.flags["BROKER_MAPPED"] and not r.execution_eligible

    full = replace(discovery_only, broker_mappings=(
        BrokerMapping("ETORO", "DEMO", "9", NOW, "one-shot lookup", True),))
    assert evaluate_eligibility(full, as_of).execution_eligible

    short = replace(full, coverage=(_cov(date(2026, 6, 1), date(2026, 10, 20), 100),))
    r = evaluate_eligibility(short, as_of)
    assert r.flags["MARKET_DATA_COVERAGE"] and not r.flags["SUFFICIENT_HISTORY"]
    assert not r.strategy_eligible and not r.execution_eligible

    stale = replace(full, coverage=(_cov(date(2016, 1, 4), date(2026, 9, 1), 2650),))
    assert not evaluate_eligibility(stale, as_of).discovery_eligible

    excluded = replace(full, exclusion_reasons=("PENNY_STOCK",))
    r = evaluate_eligibility(excluded, as_of)
    assert r.discovery_eligible and not r.strategy_eligible and not r.execution_eligible

    suspended = replace(full, suspensions=((date(2026, 10, 1), None),))
    r = evaluate_eligibility(suspended, as_of)
    assert not r.flags["LISTED_ACTIVE"] and "SUSPENDED" in r.reasons and not r.execution_eligible


def test_uk_enabled_for_discovery_only_and_phase3_design_only() -> None:
    # Owner directive 2026-10-23 (SD-088): UK discovery/research enabled; execution never.
    assert MARKETS["US"].discovery_enabled and MARKETS["UK"].discovery_enabled
    for market in ("EU", "FX"):
        assert not MARKETS[market].discovery_enabled
    assert not any(m.execution_enabled for m in MARKETS.values())
    uk = _rec("UK:VOD", "VOD", date(2000, 1, 4), currency="GBP", country="GB",
              quote_unit="GBX", tickers=(TickerInterval("VOD", "LSE", date(2000, 1, 4)),),
              coverage=(_cov(date(2010, 1, 4), date(2026, 10, 20), 4000),))
    report = evaluate_eligibility(uk, date(2026, 10, 21))
    assert "MARKET_NOT_ENABLED_FOR_DISCOVERY" not in report.reasons and report.discovery_eligible
    assert not report.execution_eligible and "NO_BROKER_MAPPING" in report.reasons
    reg = _registry(uk)
    assert reg.universe_as_of(date(2026, 10, 21)).members == ()  # default slice is US only
    assert [r.canonical_id for r in reg.universe_as_of(date(2026, 10, 21), markets=("UK",)).members]         == ["UK:VOD"]
    eu = _rec("EU:SAP", "SAP", date(2000, 1, 4), currency="EUR", country="DE",
              tickers=(TickerInterval("SAP", "XETRA", date(2000, 1, 4)),),
              coverage=(_cov(date(2010, 1, 4), date(2026, 10, 20), 4000),))
    assert "MARKET_NOT_ENABLED_FOR_DISCOVERY" in evaluate_eligibility(eu, date(2026, 10, 21)).reasons


def test_uk_records_need_quote_unit_and_valid_isin() -> None:
    base = _rec("UK:VOD", "VOD", date(2000, 1, 4), currency="GBP", country="GB",
                tickers=(TickerInterval("VOD", "LSE", date(2000, 1, 4)),))
    with pytest.raises(UniverseError, match="explicit quote unit"):
        _registry(base)
    with pytest.raises(UniverseError, match="inconsistent with currency"):
        _registry(replace(base, quote_unit="GBX", currency="USD"))
    with pytest.raises(UniverseError, match="GBX is a quote unit|invalid trading currency|inconsistent"):
        _registry(replace(base, quote_unit="GBX", currency="GBX"))
    with pytest.raises(UniverseError, match="unsupported quote unit"):
        _registry(replace(base, quote_unit="GBp"))
    with pytest.raises(UniverseError, match="invalid ISIN"):
        _registry(replace(base, quote_unit="GBX", isin="GB00BH4HKS38"))  # bad check digit
    ok = _registry(replace(base, quote_unit="GBX", isin="GB00BH4HKS39"))
    assert ok.get("UK:VOD").isin == "GB00BH4HKS39"


def test_optional_identity_fields_keep_legacy_digest_and_round_trip() -> None:
    us = _rec("US:AAA", "AAA", date(2010, 1, 4))
    legacy = _registry(us)
    assert "isin" not in legacy.to_json() and "quote_unit" not in legacy.to_json()
    uk = _rec("UK:VOD", "VOD", date(2000, 1, 4), currency="GBP", country="GB", quote_unit="GBX",
              isin="GB00BH4HKS39", tickers=(TickerInterval("VOD", "LSE", date(2000, 1, 4)),))
    reg = _registry(us, uk)
    again = MarketUniverseRegistry.from_json(reg.to_json())
    assert again.digest == reg.digest and again.get("UK:VOD").quote_unit == "GBX"


def test_identity_change_is_history_rewrite() -> None:
    uk = _rec("UK:VOD", "VOD", date(2000, 1, 4), currency="GBP", country="GB", quote_unit="GBX",
              isin="GB00BH4HKS39", tickers=(TickerInterval("VOD", "LSE", date(2000, 1, 4)),))
    reg = _registry(uk)
    with pytest.raises(UniverseError, match="rewrites recorded history"):
        reg.refresh((replace(uk, quote_unit="GBP"),), created_at=NOW, source_note="x")
    with pytest.raises(UniverseError, match="rewrites recorded history"):
        reg.refresh((replace(uk, isin="GB0007980591"),), created_at=NOW, source_note="x")


def test_snapshot_records_refused_for_history() -> None:
    snap = InstrumentRecord(
        canonical_id="US:SNP", name="Snap Corp", country="US", asset_type="COMMON_STOCK",
        currency="USD", tickers=(TickerInterval("SNP", "NYSE", date(2026, 10, 22)),),
        history_basis="SNAPSHOT", provenance=PROV, snapshot_date=date(2026, 10, 22),
    )
    reg = _registry(snap)
    old = reg.universe_as_of(date(2024, 1, 2))
    assert old.members == () and old.refused_snapshot_records == 1 and old.survivorship_risk
    now = reg.universe_as_of(date(2026, 10, 22))
    assert [r.canonical_id for r in now.members] == ["US:SNP"] and not now.survivorship_risk


def test_json_round_trip_and_tamper_detection() -> None:
    rec = _rec("US:AAA", "AAA", date(2010, 1, 4), memberships=(
        IndexMembership("NDX", date(2012, 1, 3), None, PROV),),
        coverage=(_cov(date(2016, 1, 4), date(2026, 10, 20), 2700),),
        broker_mappings=(BrokerMapping("ETORO", "DEMO", "9", NOW, "lookup", False),))
    reg = _registry(rec)
    text = reg.to_json()
    again = MarketUniverseRegistry.from_json(text)
    assert again.digest == reg.digest and again.records == reg.records
    with pytest.raises(UniverseError, match="digest"):
        MarketUniverseRegistry.from_json(text.replace('"AAA Corp"', '"AAB Corp"'))


def test_refresh_versions_and_refuses_history_rewrite_or_deletion() -> None:
    a = _rec("US:AAA", "AAA", date(2010, 1, 4))
    b = _rec("US:BBB", "BBB", date(2011, 1, 3))
    reg = _registry(a, b)
    delisted_b = replace(b, delisting_date=date(2026, 10, 1), tickers=(
        TickerInterval("BBB", "NASDAQ", date(2011, 1, 3), date(2026, 10, 1)),),
        actions=(CorporateAction("DELISTING", date(2026, 10, 1), "merger", PROV),))
    new_c = _rec("US:CCC", "CCC", date(2026, 10, 15))
    reg2, diff = reg.refresh((a, delisted_b, new_c), created_at=NOW, source_note="refresh")
    assert reg2.version == 2 and diff.added == ("US:CCC",) and diff.changed == ("US:BBB",)
    assert diff.history_rewrites == ()
    with pytest.raises(UniverseError, match="drop"):
        reg.refresh((a,), created_at=NOW, source_note="x")
    rewritten = replace(a, listing_date=date(2012, 1, 3),
                        tickers=(TickerInterval("AAA", "NASDAQ", date(2012, 1, 3)),))
    with pytest.raises(UniverseError, match="rewrites"):
        reg.refresh((rewritten, b), created_at=NOW, source_note="x")
    _, diff = reg.refresh((rewritten, b), created_at=NOW, source_note="x",
                          allow_history_correction=True)
    assert diff.history_rewrites == ("US:AAA",)


NASDAQ_FIXTURE = """Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares
AAPL|Apple Inc. - Common Stock|Q|N|N|100|N|N
QQQ|Invesco QQQ Trust, Series 1|G|N|N|100|Y|N
ZXZZT|NASDAQ TEST STOCK|G|Y|N|100|N|N
BADD|Bad Co - Common Stock|S|N|D|100|N|N
WRNTW|Some Co - Warrant|S|N|N|100|N|N
SHORT|row
File Creation Time: 1022202608:31|||||||
"""
OTHER_FIXTURE = """ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol
SPY|SPDR S&P 500 ETF Trust|P|SPY|Y|100|N|SPY
IBM|International Business Machines Corporation Common Stock|N|IBM|N|100|N|IBM
PFX|Pref Co 5.25% Preferred|N|PFX|N|100|N|PFX
AAPL|Duplicate listing|N|AAPL|N|100|N|AAPL
FOO|Unknown venue|V|FOO|N|100|N|FOO
UNH|UnitedHealth Group Incorporated Common Stock|N|UNH|N|100|N|UNH
UAL|United Airlines Holdings, Inc. - Common Stock|N|UAL|N|100|N|UAL
TSM|Taiwan Semiconductor Manufacturing Company Ltd. American Depositary Shares|N|TSM|N|100|N|TSM
SPCU|Acme Acquisition Corp Units, each consisting of one share|N|SPCU|N|100|N|SPCU
File Creation Time: 1022202608:31|||||||
"""


def test_symbol_directory_parsers_produce_snapshot_records_only() -> None:
    snap = date(2026, 10, 22)
    nas = parse_nasdaq_symbol_directory(NASDAQ_FIXTURE, kind="nasdaqlisted", snapshot_date=snap,
                                        provenance=PROV)
    other = parse_nasdaq_symbol_directory(OTHER_FIXTURE, kind="otherlisted", snapshot_date=snap,
                                          provenance=PROV)
    assert [r.canonical_id for r in nas.records] == ["US:AAPL", "US:QQQ"]
    assert dict(nas.rejected) == {
        "ZXZZT": "TEST_ISSUE", "BADD": "FINANCIAL_STATUS_D", "WRNTW": "NOT_COMMON_STOCK",
        "SHORT": "MALFORMED_ROW",
    }
    assert nas.file_creation_line and nas.file_creation_line.startswith("File Creation Time")
    assert {r.canonical_id: r.asset_type for r in other.records} == {
        "US:SPY": "ETF", "US:IBM": "COMMON_STOCK", "US:AAPL": "COMMON_STOCK",
        "US:UNH": "COMMON_STOCK", "US:UAL": "COMMON_STOCK", "US:TSM": "COMMON_STOCK"}
    assert dict(other.rejected) == {"PFX": "NOT_COMMON_STOCK", "FOO": "UNSUPPORTED_EXCHANGE",
                                    "SPCU": "NOT_COMMON_STOCK"}
    assert all(r.history_basis == "SNAPSHOT" for r in nas.records + other.records)
    merged, conflicts = merge_snapshots(nas, other)
    assert conflicts == ("US:AAPL",)
    assert [r.canonical_id for r in merged] == [
        "US:IBM", "US:QQQ", "US:SPY", "US:TSM", "US:UAL", "US:UNH"]
    reg = MarketUniverseRegistry(1, NOW, "snapshot", merged)
    assert len(reg.universe_as_of(snap).members) == 6
    truncated = OTHER_FIXTURE.rsplit("File Creation", 1)[0]
    with pytest.raises(UniverseError, match="truncated"):
        parse_nasdaq_symbol_directory(truncated, kind="otherlisted", snapshot_date=snap,
                                      provenance=PROV)
    with pytest.raises(UniverseError):
        parse_nasdaq_symbol_directory(OTHER_FIXTURE, kind="nasdaqlisted", snapshot_date=snap,
                                      provenance=PROV)


def test_review_coverage_postdating_as_of_is_refused() -> None:
    rec = _rec("US:AAA", "AAA", date(2010, 1, 4),
               coverage=(_cov(date(2020, 1, 2), date(2026, 10, 1), 1500),))
    report = evaluate_eligibility(rec, date(2020, 2, 3))
    assert not report.flags["MARKET_DATA_COVERAGE"] and not report.strategy_eligible
    assert "COVERAGE_RECORD_POSTDATES_AS_OF" in report.reasons


def test_review_refresh_detects_hidden_history_rewrites() -> None:
    base = _rec("US:AAA", "AAA", date(2010, 1, 4), suspensions=((date(2015, 1, 5), date(2015, 2, 2)),),
                exclusion_reasons=("PENNY",),
                coverage=(_cov(date(2016, 1, 4), date(2026, 10, 1), 2700),),
                broker_mappings=(BrokerMapping("ETORO", "DEMO", "9", NOW, "lookup", False),))
    reg = _registry(base)
    for change in ({"suspensions": ()}, {"exclusion_reasons": ()}, {"broker_mappings": ()},
                   {"coverage": (_cov(date(2016, 1, 4), date(2026, 9, 1), 2650),)}):
        with pytest.raises(UniverseError, match="rewrites"):
            reg.refresh((replace(base, **change),), created_at=NOW, source_note="x")  # type: ignore[arg-type]
    grown = replace(base, coverage=(_cov(date(2016, 1, 4), date(2026, 10, 20), 2713),))
    assert reg.refresh((grown,), created_at=NOW, source_note="x")[1].history_rewrites == ()
    snap = InstrumentRecord(
        canonical_id="US:SNP", name="Snap Corp", country="US", asset_type="COMMON_STOCK",
        currency="USD", tickers=(TickerInterval("SNP", "NYSE", date(2026, 10, 1)),),
        history_basis="SNAPSHOT", provenance=PROV, snapshot_date=date(2026, 10, 1))
    with pytest.raises(UniverseError, match="rewrites"):
        _registry(snap).refresh((replace(snap, snapshot_date=date(2000, 1, 3)),),
                                created_at=NOW, source_note="x")


def test_review_snapshot_refresh_closes_absent_symbols() -> None:
    def snap(cid: str, d: date) -> InstrumentRecord:
        return InstrumentRecord(
            canonical_id=cid, name=f"{cid} Inc", country="US", asset_type="COMMON_STOCK",
            currency="USD", tickers=(TickerInterval(cid[3:], "NYSE", d),),
            history_basis="SNAPSHOT", provenance=PROV, snapshot_date=d)
    d1, d2 = date(2026, 10, 1), date(2026, 10, 22)
    reg = _registry(snap("US:KEEP", d1), snap("US:GONE", d1))
    reg2, diff = reg.refresh_from_snapshot((snap("US:KEEP", d2), snap("US:NEW", d2)),
                                           snapshot_date=d2, created_at=NOW, source_note="d2")
    assert diff.added == ("US:NEW",) and diff.changed == ("US:GONE",)
    gone = reg2.get("US:GONE")
    assert gone.delisting_date == date(2026, 10, 21) and gone.exclusion_reasons
    assert reg2.get("US:KEEP").snapshot_date == d1          # history preserved
    ids = [r.canonical_id for r in reg2.universe_as_of(d2).members]
    assert ids == ["US:KEEP", "US:NEW"]
    assert "US:GONE" in [r.canonical_id for r in reg2.universe_as_of(date(2026, 10, 10)).members]
    with pytest.raises(UniverseError, match="newer"):
        reg2.refresh_from_snapshot((snap("US:KEEP", d1),), snapshot_date=d1, created_at=NOW,
                                   source_note="old")


def test_review_digest_covers_registry_metadata() -> None:
    text = _registry(_rec("US:AAA", "AAA", date(2010, 1, 4))).to_json()
    with pytest.raises(UniverseError, match="digest"):
        MarketUniverseRegistry.from_json(text.replace('"source_note": "fixture"',
                                                      '"source_note": "forged"'))
