"""SD-090 UK equity identity and GBP/GBX price normalization (offline).

London-listed shares are commonly quoted in **pence** (GBX, vendors also write
``GBp``) while some lines are quoted in pounds (GBP) or in USD/EUR. Confusing the
two is a 100x error, so:

* every UK record carries an explicit ``quote_unit`` (SD-065 enforces it);
* unit labels are matched case-sensitively: ``GBp`` = pence, ``GBP`` = pounds,
  anything ambiguous such as ``gbp`` or ``Gbp`` is refused;
* all research and accounting prices are normalized to the major unit (GBP) with
  exact ``Decimal`` division, and the conversion is recorded;
* a day-over-day jump of 50x or more is treated as a suspected unit flip and the
  whole series fails closed.

Identity: the exchange TIDM (e.g. ``SHEL``, ``BT.A``, ``BP.``) is the ticker.
Vendor-suffixed symbols (``BP.L``, ``AZN.LON``, ``BARC LN``, ``LON:BP``) are
refused instead of being guessed. ISINs are validated with their check digit.

Parsers accept owner-supplied, licence-declared files only (no network). Security
types outside ordinary shares and ETFs are rejected with a reason, never guessed.
Index membership from a *current* constituents list is recorded from its snapshot
date forward only; it is never backdated.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Sequence

from sidedeck.application.sd014_strategy_engine import StrategyBar
from sidedeck.application.sd089_exchange_calendar import CalendarError, calendar_for_exchange
from sidedeck.application.sd065_market_universe import (
    QUOTE_UNIT_CURRENCY,
    IndexMembership,
    InstrumentRecord,
    TickerInterval,
    UniverseError,
    isin_is_valid,
)
from sidedeck.application.sd065_market_universe import (
    _validate_record as validate_universe_record,
)

LISTING_SCHEMA = "sidedeck.uk_listings.v1"
MEMBERSHIP_SCHEMA = "sidedeck.uk_index_membership.v1"
HUNDRED = Decimal(100)
UNIT_FLIP_RATIO = Decimal(50)
DATA_BASES = frozenset({"REAL_DATA", "SYNTHETIC_FIXTURE", "CONTROLLED_EXECUTION_FIXTURE"})

# Exact, case-sensitive labels. "GBp" is the common vendor spelling of pence.
UNIT_LABELS: dict[str, str] = {"GBX": "GBX", "GBp": "GBX", "GBP": "GBP", "USD": "USD",
                               "EUR": "EUR"}
SECURITY_TYPES: dict[str, str] = {"ORDINARY_SHARE": "COMMON_STOCK", "ETF": "ETF"}
REJECTED_SECURITY_TYPES = frozenset({
    "INVESTMENT_TRUST", "PREFERENCE_SHARE", "ETC", "ETN", "DEPOSITARY_RECEIPT", "GDR",
    "WARRANT", "BOND", "GILT", "OEIC", "UNIT_TRUST", "SPAC", "CFD", "CRYPTO_ETN",
})
UK_INDICES = frozenset({"FTSE100", "FTSE250"})
_TIDM = re.compile(r"^[A-Z0-9]{1,4}(\.[A-Z]?)?$")
_VENDOR_FORMS = re.compile(r"(\.L|\.LON|\.LSE|\s+LN|\s+L)$|^(LON|LSE):|:LN$")


class UkMarketError(ValueError):
    pass


# --- units -------------------------------------------------------------------------------

def normalize_unit_label(label: str) -> str:
    """Map a source unit label to GBX/GBP/USD/EUR. Ambiguous spellings are refused."""
    try:
        return UNIT_LABELS[label]
    except KeyError as exc:
        raise UkMarketError(f"UNKNOWN_OR_AMBIGUOUS_UNIT:{label!r}") from exc


def to_major_unit(value: Decimal, unit: str) -> Decimal:
    """Convert a price in ``unit`` to its major currency unit (pence -> pounds)."""
    if not isinstance(value, Decimal) or not value.is_finite():
        raise UkMarketError("INVALID_PRICE")
    if unit == "GBX":
        return value / HUNDRED
    if unit in ("GBP", "USD", "EUR"):
        return value
    raise UkMarketError(f"UNSUPPORTED_UNIT:{unit}")


def from_major_unit(value: Decimal, unit: str) -> Decimal:
    if unit == "GBX":
        return value * HUNDRED
    if unit in ("GBP", "USD", "EUR"):
        return value
    raise UkMarketError(f"UNSUPPORTED_UNIT:{unit}")


# --- identity ----------------------------------------------------------------------------

def validate_tidm(symbol: str) -> str:
    """Return the LSE TIDM or raise. Vendor-suffixed or lower-case symbols are refused."""
    if symbol != symbol.strip() or not symbol:
        raise UkMarketError("INVALID_TIDM")
    if _VENDOR_FORMS.search(symbol):
        raise UkMarketError("VENDOR_SYMBOL_NOT_TIDM")
    if not _TIDM.match(symbol):
        raise UkMarketError("INVALID_TIDM")
    return symbol


@dataclass(frozen=True)
class SeriesInput:
    """Daily bars exactly as a source delivered them, in the source's declared unit."""

    canonical_id: str
    source_id: str
    source_unit_label: str
    data_basis: str
    provenance: str
    retrieved_at: datetime
    bars: tuple[StrategyBar, ...]


@dataclass(frozen=True)
class NormalizedSeries:
    canonical_id: str
    source_id: str
    data_basis: str
    provenance: str
    retrieved_at: datetime
    source_unit: str
    price_unit: str          # always the major unit (GBP for UK sterling lines)
    divisor: Decimal         # source price / divisor = major-unit price
    bars: tuple[StrategyBar, ...]


def normalize_series(series: SeriesInput, record: InstrumentRecord, now: datetime) -> NormalizedSeries:
    """Normalize a UK daily series to GBP. Every check fails closed with a reason code."""
    if series.canonical_id != record.canonical_id:
        raise UkMarketError("INSTRUMENT_MISMATCH")
    if series.data_basis not in DATA_BASES:
        raise UkMarketError("UNKNOWN_DATA_BASIS")
    if not series.provenance.strip() or not series.source_id.strip():
        raise UkMarketError("MISSING_PROVENANCE")
    if series.retrieved_at.tzinfo is None or now.tzinfo is None:
        raise UkMarketError("NAIVE_TIMESTAMP")
    if series.retrieved_at > now:
        raise UkMarketError("FUTURE_RETRIEVAL_TIME")
    if record.quote_unit is None:
        raise UkMarketError("RECORD_QUOTE_UNIT_MISSING")
    unit = normalize_unit_label(series.source_unit_label)
    if QUOTE_UNIT_CURRENCY[unit] != record.currency:
        raise UkMarketError("UNIT_CURRENCY_MISMATCH")
    if not series.bars:
        raise UkMarketError("NO_BARS")
    ordered = sorted(series.bars, key=lambda b: b.day)
    if len({b.day for b in ordered}) != len(ordered):
        raise UkMarketError("DUPLICATE_BAR")
    for b in ordered:
        if min(b.open, b.high, b.low, b.close) <= 0 or b.volume < 0:
            raise UkMarketError("NON_POSITIVE_PRICE")
    cal = calendar_for_exchange(record.tickers[-1].exchange)
    for b in ordered:
        # A bar is a complete daily bar only if it was retrieved after that session closed
        # (exchange-local day, half days honoured). A mid-session snapshot is refused.
        try:
            session = cal.session(b.day)
        except CalendarError as exc:
            raise UkMarketError("CALENDAR_UNCOVERED") from exc
        if session is None:
            raise UkMarketError(f"NON_SESSION_BAR:{b.day.isoformat()}")
        if series.retrieved_at < session.close_utc:
            raise UkMarketError(f"BAR_NOT_COMPLETE_AT_RETRIEVAL:{b.day.isoformat()}")
    for prev, cur in zip(ordered, ordered[1:]):
        if prev.close > 0 and cur.close > 0:
            ratio = cur.close / prev.close
            if ratio >= UNIT_FLIP_RATIO or ratio <= 1 / UNIT_FLIP_RATIO:
                raise UkMarketError(f"SUSPECTED_UNIT_FLIP:{cur.day.isoformat()}")
    divisor = HUNDRED if unit == "GBX" else Decimal(1)
    bars = tuple(
        StrategyBar(b.day, to_major_unit(b.open, unit), to_major_unit(b.high, unit),
                    to_major_unit(b.low, unit), to_major_unit(b.close, unit), b.volume)
        for b in ordered
    )
    return NormalizedSeries(
        series.canonical_id, series.source_id, series.data_basis, series.provenance,
        series.retrieved_at, unit, QUOTE_UNIT_CURRENCY[unit], divisor, bars,
    )


@dataclass(frozen=True)
class QuoteInput:
    canonical_id: str
    source_id: str
    unit_label: str
    bid: Decimal
    ask: Decimal
    quoted_at: datetime
    data_basis: str
    provenance: str


@dataclass(frozen=True)
class NormalizedQuote:
    canonical_id: str
    source_id: str
    data_basis: str
    provenance: str
    quoted_at: datetime
    source_unit: str
    price_unit: str
    bid: Decimal
    ask: Decimal
    mid: Decimal
    spread_bps: Decimal


def normalize_quote(
    quote: QuoteInput, record: InstrumentRecord, now: datetime, *, max_age: timedelta,
) -> NormalizedQuote:
    if quote.canonical_id != record.canonical_id:
        raise UkMarketError("INSTRUMENT_MISMATCH")
    if quote.data_basis not in DATA_BASES:
        raise UkMarketError("UNKNOWN_DATA_BASIS")
    if not quote.provenance.strip():
        raise UkMarketError("MISSING_PROVENANCE")
    if quote.quoted_at.tzinfo is None or now.tzinfo is None:
        raise UkMarketError("NAIVE_TIMESTAMP")
    if quote.quoted_at > now:
        raise UkMarketError("FUTURE_QUOTE")
    if now - quote.quoted_at > max_age:
        raise UkMarketError("STALE_QUOTE")
    unit = normalize_unit_label(quote.unit_label)
    if QUOTE_UNIT_CURRENCY[unit] != record.currency:
        raise UkMarketError("UNIT_CURRENCY_MISMATCH")
    bid, ask = to_major_unit(quote.bid, unit), to_major_unit(quote.ask, unit)
    if bid <= 0 or ask <= 0:
        raise UkMarketError("NON_POSITIVE_QUOTE")
    if ask < bid:
        raise UkMarketError("CROSSED_QUOTE")
    mid = (bid + ask) / 2
    spread_bps = (ask - bid) / mid * Decimal(10_000)
    return NormalizedQuote(quote.canonical_id, quote.source_id, quote.data_basis,
                           quote.provenance, quote.quoted_at, unit, QUOTE_UNIT_CURRENCY[unit],
                           bid, ask, mid, spread_bps)


# --- owner-supplied listing and membership files -----------------------------------------

LISTING_COLUMNS = ("tidm", "isin", "name", "security_type", "quote_unit", "currency",
                   "listing_date", "delisting_date", "tidm_start", "tidm_end", "source", "as_of")
MEMBERSHIP_COLUMNS = ("index_id", "isin", "start", "end", "basis", "source")


@dataclass(frozen=True)
class UkParseReport:
    records: tuple[InstrumentRecord, ...]
    rejected: tuple[tuple[str, str], ...]  # (row key, reason)


def _opt_date(text: str) -> date | None:
    return date.fromisoformat(text) if text.strip() else None


def parse_uk_listings(text: str, *, licence_note: str) -> UkParseReport:
    """Parse a ``sidedeck.uk_listings.v1`` CSV into SD-065 records.

    Rows sharing an ISIN form one record with several dated TIDM intervals (ticker
    changes). Conflicting attributes for the same ISIN reject the instrument.
    Rows without a listing date produce SNAPSHOT-basis records (no history use).
    """
    if not licence_note.strip():
        raise UkMarketError("licence/provenance note required for owner-supplied files")
    reader = csv.DictReader(io.StringIO(text))
    if tuple(reader.fieldnames or ()) != LISTING_COLUMNS:
        raise UkMarketError(f"unexpected header; expected {','.join(LISTING_COLUMNS)}")
    rejected: list[tuple[str, str]] = []
    groups: dict[str, list[dict[str, str]]] = {}
    for row in reader:
        key = row.get("isin") or row.get("tidm") or "?"
        if any(row.get(col) is None for col in LISTING_COLUMNS) or None in row:
            rejected.append((key, "MALFORMED_ROW"))
            continue
        try:
            validate_tidm(row["tidm"])
            stype = row["security_type"].strip()
            if not stype:
                raise UkMarketError("MISSING_SECURITY_TYPE")
            if stype in REJECTED_SECURITY_TYPES:
                raise UkMarketError(f"UNSUPPORTED_SECURITY_TYPE:{stype}")
            if stype not in SECURITY_TYPES:
                raise UkMarketError(f"UNKNOWN_SECURITY_TYPE:{stype}")
            normalize_unit_label(row["quote_unit"])
            isin = row["isin"].strip()
            if not isin:
                raise UkMarketError("MISSING_ISIN")
            if not isin_is_valid(isin):
                raise UkMarketError("INVALID_ISIN")
            for name in ("listing_date", "delisting_date", "tidm_start", "tidm_end", "as_of"):
                _opt_date(row[name])
            if not row["as_of"].strip() or not row["source"].strip():
                raise UkMarketError("MISSING_SOURCE_OR_AS_OF")
        except (UkMarketError, ValueError, KeyError) as exc:
            rejected.append((key, str(exc).split(";")[0]))
            continue
        groups.setdefault(isin, []).append(row)
    records: list[InstrumentRecord] = []
    for isin, rows in sorted(groups.items()):
        fixed = {(r["name"], r["security_type"], r["quote_unit"], r["currency"],
                  r["listing_date"], r["delisting_date"]) for r in rows}
        if len(fixed) != 1:
            rejected.append((isin, "CONFLICTING_ROWS_FOR_ISIN"))
            continue
        first = rows[0]
        unit = normalize_unit_label(first["quote_unit"])
        listing = _opt_date(first["listing_date"])
        snapshot = max(date.fromisoformat(r["as_of"]) for r in rows)
        intervals = tuple(sorted(
            (TickerInterval(r["tidm"], "LSE",
                            _opt_date(r["tidm_start"]) or listing or snapshot,
                            _opt_date(r["tidm_end"])) for r in rows),
            key=lambda t: t.start,
        ))
        try:
            record = InstrumentRecord(
                canonical_id=f"UK:{isin}", name=first["name"].strip(), country=isin[:2],
                asset_type=SECURITY_TYPES[first["security_type"].strip()],
                currency=first["currency"].strip(), tickers=intervals,
                history_basis="POINT_IN_TIME" if listing else "SNAPSHOT",
                provenance=f"{first['source'].strip()} | {licence_note.strip()}",
                listing_date=listing, delisting_date=_opt_date(first["delisting_date"]),
                snapshot_date=None if listing else snapshot, isin=isin, quote_unit=unit,
            )
            validate_universe_record(record)  # every SD-065 rule applies
        except UniverseError as exc:
            rejected.append((isin, f"RECORD_INVALID:{exc}"))
            continue
        records.append(record)
    return UkParseReport(tuple(records), tuple(rejected))


def apply_index_memberships(
    records: Sequence[InstrumentRecord], text: str, *, licence_note: str, snapshot_date: date,
) -> tuple[tuple[InstrumentRecord, ...], tuple[tuple[str, str], ...]]:
    """Attach dated FTSE memberships from a ``sidedeck.uk_index_membership.v1`` CSV.

    ``basis=SNAPSHOT`` rows (a current constituents list) must have ``start`` equal to
    ``snapshot_date`` (the list date) and no ``end``; they are never backdated. ``POINT_IN_TIME`` rows need a
    dated review source. Unknown ISINs or indices are rejected.
    """
    if not licence_note.strip():
        raise UkMarketError("licence/provenance note required for owner-supplied files")
    reader = csv.DictReader(io.StringIO(text))
    if tuple(reader.fieldnames or ()) != MEMBERSHIP_COLUMNS:
        raise UkMarketError(f"unexpected header; expected {','.join(MEMBERSHIP_COLUMNS)}")
    by_isin = {r.isin: r for r in records if r.isin}
    added: dict[str, list[IndexMembership]] = {}
    rejected: list[tuple[str, str]] = []
    for row in reader:
        if any(row.get(col) is None for col in MEMBERSHIP_COLUMNS) or None in row:
            rejected.append(((row.get("isin") or "?").strip(), "MALFORMED_ROW"))
            continue
        isin = row["isin"].strip()
        try:
            if row["index_id"] not in UK_INDICES:
                raise UkMarketError("UNKNOWN_INDEX")
            if isin not in by_isin:
                raise UkMarketError("UNKNOWN_ISIN")
            start, end = date.fromisoformat(row["start"]), _opt_date(row["end"])
            if row["basis"] == "SNAPSHOT":
                if end is not None:
                    raise UkMarketError("SNAPSHOT_MEMBERSHIP_CANNOT_HAVE_END")
                if start != snapshot_date:
                    raise UkMarketError("SNAPSHOT_MEMBERSHIP_BACKDATED")
            elif row["basis"] != "POINT_IN_TIME":
                raise UkMarketError("UNKNOWN_BASIS")
            if not row["source"].strip():
                raise UkMarketError("MISSING_SOURCE")
            if end is not None and end < start:
                raise UkMarketError("END_BEFORE_START")
        except (UkMarketError, ValueError) as exc:
            rejected.append((isin or "?", str(exc)))
            continue
        source = f"{row['basis']}: {row['source'].strip()} | {licence_note.strip()}"
        added.setdefault(isin, []).append(IndexMembership(row["index_id"], start, end, source))
    out: list[InstrumentRecord] = []
    for r in records:
        merged = r.memberships + tuple(
            m for m in dict.fromkeys(added.get(r.isin or "", ())) if m not in r.memberships
        )
        updated = replace(r, memberships=merged)
        try:
            validate_universe_record(updated)
        except UniverseError as exc:
            rejected.append((r.isin or r.canonical_id, f"RECORD_INVALID:{exc}"))
            updated = r
        out.append(updated)
    return tuple(out), tuple(rejected)


# --- candidate watchlist (names only; identity unverified) -------------------------------

@dataclass(frozen=True)
class UkCandidate:
    name: str
    proposed_tidm: str
    expected_isin: str
    identity_status: str
    note: str


# These are *candidate names* from the owner directive. The TIDMs and ISINs are recalled
# reference values used only to cross-check a future sourced file; they are not sourced
# identity and never create registry records by themselves.
UK_CANDIDATE_WATCHLIST: tuple[UkCandidate, ...] = (
    UkCandidate("BP p.l.c.", "BP.", "GB0007980591", "UNVERIFIED_PENDING_SOURCE", ""),
    UkCandidate("Shell plc", "SHEL", "GB00BP6MXD84", "UNVERIFIED_PENDING_SOURCE",
                "line changed at the January 2022 share unification; verify current ISIN"),
    UkCandidate("HSBC Holdings plc", "HSBA", "GB0005405286", "UNVERIFIED_PENDING_SOURCE", ""),
    UkCandidate("AstraZeneca PLC", "AZN", "GB0009895292", "UNVERIFIED_PENDING_SOURCE", ""),
    UkCandidate("Unilever PLC", "ULVR", "GB00B10RZP78", "UNVERIFIED_PENDING_SOURCE",
                "corporate actions around the ice cream demerger may have changed the line; "
                "verify current ISIN and share basis"),
)


def candidate_identity_check(
    candidate: UkCandidate, records: Sequence[InstrumentRecord], as_of: date,
) -> tuple[str, InstrumentRecord | None]:
    """Match a candidate to a sourced record by TIDM on ``as_of`` and expected ISIN."""
    matches = [r for r in records if (t := r.ticker_on(as_of)) is not None
               and t.exchange == "LSE" and t.ticker == candidate.proposed_tidm]
    if not matches:
        return "NO_SOURCED_RECORD", None
    if len(matches) > 1:
        return "AMBIGUOUS_TIDM", None
    record = matches[0]
    if record.isin != candidate.expected_isin:
        return "ISIN_DIFFERS_FROM_EXPECTED_REVIEW_REQUIRED", record
    return "MATCHED_SOURCED_RECORD", record
