"""SD-096 UK morning acceptance runner (offline).

``python -m sidedeck.application.sd096_uk_acceptance`` produces one JSON report with
three clearly separated parts:

1. ``genuine_data`` - inventory of owner-supplied UK files under ``data/uk`` (ignored
   by git). With no licensed files the five candidate names (BP, Shell, HSBC,
   AstraZeneca, Unilever) correctly ABSTAIN: identity unsourced, no market data.
2. ``fixture_scan`` - the full UK pipeline (identity, GBX->GBP, XLON calendar,
   DAY/SWING/POSITION rankings, native signals, decisions) on a SYNTHETIC_FIXTURE
   universe with ``ZZ``-prefixed synthetic ISINs. Plumbing evidence only.
3. ``simulated_trade`` - one SIMULATION buy -> position -> exit -> reconciliation on
   the fixture, driven by a separately labelled CONTROLLED_EXECUTION_FIXTURE intent
   (no strategy is admitted, so no research signal is turned into an order), plus
   the negative scenario matrix.

No network, credentials, broker, eToro request or order path is involved.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import tempfile
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_FLOOR, Decimal
from pathlib import Path
from typing import Any, Callable

from sidedeck.application.sd014_strategy_engine import StrategyBar
from sidedeck.application.sd065_market_universe import (
    InstrumentRecord,
    MarketUniverseRegistry,
    SourceCoverage,
    isin_is_valid,
)
from sidedeck.application.sd089_exchange_calendar import XLON
from sidedeck.application.sd090_uk_market import (
    UK_CANDIDATE_WATCHLIST,
    NormalizedQuote,
    QuoteInput,
    SeriesInput,
    UkMarketError,
    candidate_identity_check,
    normalize_quote,
    parse_uk_listings,
)
from sidedeck.application.sd092_uk_scanner import UkScanResult, run_uk_scan
from sidedeck.application.sd093_uk_sim_desk import (
    FillPlan,
    SimDeskError,
    SimInterruption,
    SimVenueMapping,
    UkOrderIntent,
    UkSimDesk,
)

FIXTURE_BASIS = "SYNTHETIC_FIXTURE"
FIXTURE_SOURCE = "SD096_SYNTHETIC_UK"
FIXTURE_PROVENANCE = "sd096 synthetic UK generator; not market data"
CUTOFF = date(2026, 10, 22)                                   # Thursday, completed LSE session
SCAN_NOW = datetime(2026, 10, 23, 6, 30, tzinfo=UTC)         # 07:30 BST, before the open
TRADE_AT = datetime(2026, 10, 23, 8, 0, tzinfo=UTC)          # 09:00 BST, LSE open
EXIT_AT = datetime(2026, 10, 23, 13, 0, tzinfo=UTC)          # 14:00 BST
SIM_BOOK = "SIM_UK_SWING"


# --- genuine data inventory -------------------------------------------------------------

def genuine_data_inventory(data_dir: Path, as_of: date) -> dict[str, Any]:
    listings = sorted(data_dir.glob("uk_listings*.csv")) if data_dir.is_dir() else []
    bars = sorted((data_dir / "bars").glob("*.csv")) if (data_dir / "bars").is_dir() else []
    records: tuple[InstrumentRecord, ...] = ()
    rejected: list[list[str]] = []
    for path in listings:
        licence = path.with_suffix(".licence.txt")
        if not licence.is_file():
            rejected.append([path.name, "MISSING_LICENCE_NOTE"])
            continue
        report = parse_uk_listings(path.read_text(encoding="utf-8"),
                                   licence_note=licence.read_text(encoding="utf-8"))
        records += report.records
        rejected += [list(r) for r in report.rejected]
    candidates = []
    for cand in UK_CANDIDATE_WATCHLIST:
        status, record = candidate_identity_check(cand, records, as_of)
        reasons = [status]
        if record is None or not bars:
            reasons.append("NO_APPROVED_MARKET_DATA")
        candidates.append({
            "name": cand.name, "proposed_tidm": cand.proposed_tidm,
            "expected_isin_unverified": cand.expected_isin,
            "identity_status": cand.identity_status, "result": "ABSTAIN", "reasons": reasons,
            "note": cand.note,
        })
    status = "GENUINE_UK_DATA_PRESENT_REVIEW_REQUIRED" if records and bars \
        else "NO_GENUINE_UK_DATA"
    return {
        "data_dir": str(data_dir), "listing_files": [p.name for p in listings],
        "bar_files": len(bars), "sourced_records": len(records), "rejected": rejected,
        "status": status, "candidates": candidates,
        "blocker": None if status != "NO_GENUINE_UK_DATA" else (
            "No licensed UK listings, FTSE membership or OHLCV exist locally. Approved sources: "
            "owner-supplied licensed files (none supplied) or a bounded owner authorization "
            "(SD-094). Calendar corroboration (gov.uk) also pending."
        ),
    }


# --- synthetic fixture --------------------------------------------------------------------

def fixture_isin(n: int) -> str:
    payload = f"ZZSYN{n:06d}"
    for digit in range(10):
        if isin_is_valid(payload + str(digit)):
            return payload + str(digit)
    raise ValueError("no check digit")  # pragma: no cover - Luhn always has one


def _walk(seed: int, days: tuple[date, ...], start: Decimal) -> tuple[StrategyBar, ...]:
    """Deterministic pseudo-random walk (linear congruential), Decimal only."""
    state = seed * 7919 + 17
    price = start
    volume = Decimal(400_000 + (seed * 37_000) % 4_000_000)
    bars = []
    for day in days:
        state = (state * 1103515245 + 12345) % (2**31)
        step = (Decimal(state % 2001) - Decimal(1000)) / Decimal(60_000)
        drift = Decimal(seed % 5 - 1) / Decimal(10_000)
        close = (price * (1 + step + drift)).quantize(Decimal("0.01"))
        high = (max(price, close) * Decimal("1.006")).quantize(Decimal("0.01"))
        low = (min(price, close) * Decimal("0.994")).quantize(Decimal("0.01"))
        bars.append(StrategyBar(day, price, high, low, close, volume))
        price = close
    return tuple(bars)


@dataclass(frozen=True)
class UkFixture:
    registry: MarketUniverseRegistry
    series: dict[str, SeriesInput]
    quotes: dict[str, QuoteInput]
    benchmark: SeriesInput
    listing_rejections: tuple[tuple[str, str], ...]


FIXTURE_ROWS: tuple[tuple[int, str, str, str, str], ...] = (
    # (n, tidm, security_type, quote_unit label in listing, series unit label)
    (1, "SYA", "ORDINARY_SHARE", "GBX", "GBp"),
    (2, "SYB", "ORDINARY_SHARE", "GBX", "GBX"),
    (3, "SYC", "ORDINARY_SHARE", "GBX", "GBp"),
    (4, "SYD", "ORDINARY_SHARE", "GBX", "GBX"),
    (5, "SYE", "ORDINARY_SHARE", "GBX", "GBp"),
    (6, "SYF", "ORDINARY_SHARE", "GBX", "GBX"),
    (7, "SYG.A", "ORDINARY_SHARE", "GBX", "GBp"),
    (8, "SYH", "ETF", "GBP", "GBP"),
    (9, "SYI", "ORDINARY_SHARE", "GBX", "gbp"),      # ambiguous unit label -> excluded
    (10, "SYJ", "ORDINARY_SHARE", "GBX", "GBX"),     # unit flip mid-series -> excluded
    (11, "SYK", "ORDINARY_SHARE", "GBX", "GBX"),     # stale series -> excluded
    (12, "SYX", "ETF", "GBP", "GBP"),                # benchmark proxy
)


def build_uk_fixture() -> UkFixture:
    days = XLON.sessions_between(date(2025, 6, 2), CUTOFF)
    listing = io.StringIO()
    writer = csv.writer(listing, lineterminator="\n")
    writer.writerow(("tidm", "isin", "name", "security_type", "quote_unit", "currency",
                     "listing_date", "delisting_date", "tidm_start", "tidm_end", "source",
                     "as_of"))
    for n, tidm, stype, unit, _ in FIXTURE_ROWS:
        writer.writerow((tidm, fixture_isin(n), f"Synthetic UK {n:03d}", stype, unit, "GBP",
                         "2020-01-02", "", "", "", "sd096 synthetic listing", "2026-10-22"))
    # Rows that must be rejected rather than guessed.
    writer.writerow(("SYT", fixture_isin(20), "Synthetic Trust", "INVESTMENT_TRUST", "GBX",
                     "GBP", "2020-01-02", "", "", "", "sd096 synthetic listing", "2026-10-22"))
    writer.writerow(("SYV.L", fixture_isin(21), "Synthetic Vendor", "ORDINARY_SHARE", "GBX",
                     "GBP", "2020-01-02", "", "", "", "sd096 synthetic listing", "2026-10-22"))
    writer.writerow(("SYW", fixture_isin(22), "Synthetic Unknown", "STAPLED_UNIT", "GBX",
                     "GBP", "2020-01-02", "", "", "", "sd096 synthetic listing", "2026-10-22"))
    parsed = parse_uk_listings(listing.getvalue(), licence_note=FIXTURE_PROVENANCE)
    retrieved = datetime(2026, 10, 22, 18, 0, tzinfo=UTC)
    records: list[InstrumentRecord] = []
    series: dict[str, SeriesInput] = {}
    quotes: dict[str, QuoteInput] = {}
    by_isin = {r.isin: r for r in parsed.records}
    for n, _, _, unit, series_unit in FIXTURE_ROWS:
        record = by_isin[fixture_isin(n)]
        start = Decimal(4 + n * 3) if unit == "GBP" else Decimal(250 + n * 140)
        bars = _walk(n, days, start)
        if n == 10:  # a vendor switching from pence to pounds mid-series
            bars = bars[:-30] + tuple(
                StrategyBar(b.day, b.open / 100, b.high / 100, b.low / 100, b.close / 100,
                            b.volume) for b in bars[-30:])
        if n == 11:
            bars = bars[:-3]
        cov = SourceCoverage(FIXTURE_SOURCE, "1D", bars[0].day, bars[-1].day, len(bars),
                             FIXTURE_PROVENANCE)
        records.append(InstrumentRecord(**{**{f: getattr(record, f)
                                               for f in record.__dataclass_fields__},
                                            "coverage": (cov,)}))
        cid = record.canonical_id
        series[cid] = SeriesInput(cid, FIXTURE_SOURCE, series_unit, FIXTURE_BASIS,
                                  FIXTURE_PROVENANCE, retrieved, bars)
        last = bars[-1].close
        tick = Decimal("0.1") if unit == "GBX" else Decimal("0.001")
        quotes[cid] = QuoteInput(cid, FIXTURE_SOURCE, series_unit if series_unit != "gbp" else
                                 "GBX", (last * Decimal("0.9995")).quantize(tick),
                                 (last * Decimal("1.0005")).quantize(tick),
                                 TRADE_AT - timedelta(seconds=20), FIXTURE_BASIS,
                                 FIXTURE_PROVENANCE)
    registry = MarketUniverseRegistry(1, retrieved, "sd096 synthetic UK fixture", tuple(records))
    bench_cid = by_isin[fixture_isin(12)].canonical_id
    return UkFixture(registry, series, quotes, series[bench_cid], parsed.rejected)


def run_fixture_scan(fixture: UkFixture, now: datetime = SCAN_NOW) -> UkScanResult:
    return run_uk_scan(fixture.registry, fixture.series, CUTOFF, now, data_basis=FIXTURE_BASIS,
                       benchmark=fixture.benchmark)


# --- simulated trade ------------------------------------------------------------------------

def _mapping(cid: str, asset_type: str) -> SimVenueMapping:
    return SimVenueMapping(cid, "SIDEDECK_SIM_LSE", f"SIM:{cid}", asset_type, Decimal("10"),
                           Decimal("1"))


def _quote(
    fixture: UkFixture, cid: str, at: datetime, move: Decimal = Decimal(0)
) -> NormalizedQuote:
    raw = fixture.quotes[cid]
    shifted = QuoteInput(raw.canonical_id, raw.source_id, raw.unit_label,
                         raw.bid * (1 + move), raw.ask * (1 + move),
                         at - timedelta(seconds=20), raw.data_basis, raw.provenance)
    return normalize_quote(shifted, fixture.registry.get(cid), at, max_age=timedelta(minutes=5))


def simulated_trade(fixture: UkFixture, cid: str, workdir: Path) -> dict[str, Any]:
    record = fixture.registry.get(cid)
    desk = UkSimDesk(workdir / "sim_uk_swing.sqlite3", book_id=SIM_BOOK,
                     capital_gbp=Decimal("1000"), mappings={cid: _mapping(cid, record.asset_type)})
    entry_quote = _quote(fixture, cid, TRADE_AT)
    qty = (Decimal("150") / entry_quote.ask).to_integral_value(rounding=ROUND_FLOOR)
    buy = UkOrderIntent("uk-sim-entry-1", SIM_BOOK, cid, "BUY", qty, entry_quote.ask,
                        "CONTROLLED_EXECUTION_FIXTURE", TRADE_AT)
    entry = desk.submit(buy, entry_quote, TRADE_AT)
    after_entry = desk.reconcile()
    exit_quote = _quote(fixture, cid, EXIT_AT, Decimal("0.004"))
    sell = UkOrderIntent("uk-sim-exit-1", SIM_BOOK, cid, "SELL", entry.filled_quantity,
                         exit_quote.bid, "CONTROLLED_EXECUTION_FIXTURE", EXIT_AT)
    exit_ = desk.submit(sell, exit_quote, EXIT_AT)
    final = desk.reconcile()
    raw = fixture.quotes[cid]
    return {
        "label": "SIMULATION", "intent_source": "CONTROLLED_EXECUTION_FIXTURE",
        "why_fixture": "no admitted UK strategy exists; research decisions were not ELIGIBLE",
        "instrument": {"canonical_id": cid, "tidm": record.tickers[-1].ticker,
                       "isin": record.isin, "quote_unit": record.quote_unit},
        "gbx_to_gbp": {"source_unit": entry_quote.source_unit,
                       "source_ask": str(raw.ask), "normalized_ask_gbp": str(entry_quote.ask)},
        "entry": _result(entry), "position_after_entry": [vars(p) for p in after_entry.positions],
        "exit": _result(exit_),
        "final_reconciliation": {
            "status": final.status, "cash_gbp": str(final.cash_gbp),
            "realized_pnl_gbp": str(final.realized_pnl_gbp), "fees_gbp": str(final.fees_gbp),
            "open_positions": len(final.positions), "issues": list(final.issues),
        },
        "fill_basis": "SIMULATED_LOCAL",
    }


def _result(r: Any) -> dict[str, Any]:
    return {"status": r.status, "reason": r.reason, "filled_quantity": str(r.filled_quantity),
            "avg_price_gbp": None if r.avg_price_gbp is None else str(r.avg_price_gbp),
            "fees_gbp": str(r.fees_gbp), "label": r.label}


def scenario_matrix(fixture: UkFixture, cid: str, workdir: Path) -> dict[str, Any]:
    """Each scenario on a fresh simulation book; returns the observed outcome codes."""
    record = fixture.registry.get(cid)
    out: dict[str, Any] = {}
    counter = iter(range(1000))

    def desk(mappings: dict[str, SimVenueMapping] | None = None) -> UkSimDesk:
        return UkSimDesk(workdir / f"scenario_{next(counter)}.sqlite3", book_id=SIM_BOOK,
                         capital_gbp=Decimal("1000"),
                         mappings={cid: _mapping(cid, record.asset_type)}
                         if mappings is None else mappings)

    def intent(iid: str, qty: Decimal, at: datetime, side: str = "BUY",
               limit: Decimal | None = None) -> UkOrderIntent:
        q = _quote(fixture, cid, at)
        return UkOrderIntent(iid, SIM_BOOK, cid, side, qty,
                             limit if limit is not None else (q.ask if side == "BUY" else q.bid),
                             "CONTROLLED_EXECUTION_FIXTURE", at)

    def run(name: str, fn: Callable[[], str]) -> None:
        try:
            out[name] = fn()
        except (SimDeskError, UkMarketError) as exc:
            out[name] = f"REFUSED:{exc}"

    q_open = _quote(fixture, cid, TRADE_AT)
    run("stale_market_data", lambda: desk().submit(
        intent("s1", Decimal(1), TRADE_AT + timedelta(minutes=10)), q_open,
        TRADE_AT + timedelta(minutes=10)).reason)
    run("missing_broker_mapping", lambda: desk({}).submit(
        intent("s2", Decimal(1), TRADE_AT), q_open, TRADE_AT).reason)
    closed = datetime(2026, 10, 24, 10, 0, tzinfo=UTC)  # Saturday
    run("market_closed", lambda: desk().submit(
        intent("s3", Decimal(1), TRADE_AT), _quote(fixture, cid, closed), closed).reason)
    run("after_close_same_day", lambda: desk().submit(
        intent("s3b", Decimal(1), TRADE_AT), _quote(fixture, cid, datetime(
            2026, 10, 23, 15, 31, tzinfo=UTC)), datetime(2026, 10, 23, 15, 31, tzinfo=UTC)).reason)
    tiny = (Decimal("5") / q_open.ask).quantize(Decimal(1), rounding=ROUND_FLOOR) or Decimal(1)
    run("minimum_order_violation", lambda: desk().submit(
        intent("s4", tiny if tiny * q_open.ask < 10 else Decimal(1), TRADE_AT), q_open,
        TRADE_AT).reason if q_open.ask < 10 else "NOT_APPLICABLE_PRICE_ABOVE_MINIMUM")
    run("gbx_ambiguous_unit_label", lambda: normalize_quote(QuoteInput(
        cid, FIXTURE_SOURCE, "gbp", Decimal(100), Decimal(101), TRADE_AT, FIXTURE_BASIS,
        FIXTURE_PROVENANCE), record, TRADE_AT, max_age=timedelta(minutes=5)).source_unit)

    def partial() -> str:
        d = desk()
        r = d.submit(intent("s5", Decimal(10), TRADE_AT), q_open, TRADE_AT,
                     plan=FillPlan(fill_ratio=Decimal("0.4")))
        return f"{r.status}:{r.filled_quantity}/10:{d.reconcile().status}"
    run("partial_fill", partial)

    def duplicate() -> str:
        d = desk()
        first = d.submit(intent("s6", Decimal(2), TRADE_AT), q_open, TRADE_AT)
        second = d.submit(intent("s6", Decimal(2), TRADE_AT), q_open, TRADE_AT)
        fills = sum(1 for k, _, _ in d.events() if k in ("FILLED", "PARTIALLY_FILLED"))
        return f"{first.status}->{second.reason}:fills={fills}"
    run("duplicate_order", duplicate)

    def interrupted() -> str:
        d = desk()
        try:
            d.submit(intent("s7", Decimal(2), TRADE_AT), q_open, TRADE_AT,
                     plan=FillPlan(crash_after_venue=True))
        except SimInterruption:
            pass
        blocked = d.submit(intent("s7b", Decimal(1), TRADE_AT), q_open, TRADE_AT).reason
        recovered = d.recover(TRADE_AT + timedelta(minutes=1))
        submitted = sum(1 for k, _, _ in d.events() if k == "SUBMITTED")
        return (f"blocked={blocked};recovered={recovered[0].status};"
                f"submissions={submitted};recon={d.reconcile().status}")
    run("interrupted_execution", interrupted)

    def unknown_exit() -> str:
        d = desk()
        d.submit(intent("s8", Decimal(2), TRADE_AT), q_open, TRADE_AT)
        try:
            d.submit(intent("s8x", Decimal(2), EXIT_AT, side="SELL"), _quote(fixture, cid, EXIT_AT),
                     EXIT_AT, plan=FillPlan(crash_after_venue=True, venue_lookup_available=False))
        except SimInterruption:
            pass
        res = d.recover(EXIT_AT + timedelta(minutes=1))
        rec = d.reconcile()
        nxt = d.submit(intent("s8y", Decimal(1), EXIT_AT), _quote(fixture, cid, EXIT_AT),
                       EXIT_AT).reason
        return (f"{res[0].status};kill_switch={d.kill_switch};recon={rec.status};"
                f"position={[p.status for p in rec.positions]};next_order={nxt}")
    run("unknown_exit_outcome", unknown_exit)

    def protected() -> str:
        try:
            UkSimDesk(workdir / "protected.sqlite3", book_id="ETORO_DEMO_BASELINE",
                      capital_gbp=Decimal(1000), mappings={})
            return "NOT_REFUSED"
        except SimDeskError as exc:
            refused = str(exc)
        d = desk()
        other = UkOrderIntent("s9", "SIM_UK_POSITION", cid, "BUY", Decimal(1), q_open.ask,
                              "CONTROLLED_EXECUTION_FIXTURE", TRADE_AT)
        return f"{refused};cross_book={d.submit(other, q_open, TRADE_AT).reason}"
    run("protected_portfolio_separation", protected)
    return out


def run_acceptance(data_dir: Path, workdir: Path) -> dict[str, Any]:
    workdir.mkdir(parents=True, exist_ok=True)
    fixture = build_uk_fixture()
    scan = run_fixture_scan(fixture)
    swing = scan.shortlists.get("SWING")
    chosen = swing.candidates[0].canonical_id if swing and swing.candidates else \
        sorted(fixture.series)[0]
    return {
        "report": "sd096.uk_morning_acceptance.v1",
        "genuine_data": genuine_data_inventory(data_dir, CUTOFF),
        "calendar": {"id": XLON.calendar_id, "timezone": XLON.timezone,
                     "continuous_hours_local": "08:00-16:30", "half_day_close_local": "12:30",
                     "source_status": XLON.source_status, "source_note": XLON.source_note},
        "fixture_scan": {"data_basis": FIXTURE_BASIS,
                         "warning": "Synthetic plumbing only: not market coverage or signals.",
                         "listing_rejections": [list(r) for r in fixture.listing_rejections],
                         **scan.summary()},
        "simulated_trade": simulated_trade(fixture, chosen, workdir),
        "scenarios": scenario_matrix(fixture, chosen, workdir),
        "execution_permission": "NOT_GRANTED",
        "etoro_uk_demo_readiness": "NOT_READY_BLOCKED_OWNER (see docs/SD088_UK_EQUITY_INTEGRATION.md)",
        "us_msft_pilot": "UNTOUCHED (no SD-053/SD-057/SD-058 file, digest, unlock or budget used)",
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="SD-096 UK morning acceptance (offline)")
    parser.add_argument("--data-dir", type=Path, default=Path("data/uk"))
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="sd096-") as tmp:
        print(json.dumps(run_acceptance(args.data_dir, Path(tmp)), indent=2, sort_keys=True,
                         default=str))


if __name__ == "__main__":
    main()
