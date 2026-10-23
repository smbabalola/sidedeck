"""SD-065 Market Universe Manager: versioned, point-in-time instrument registry.

Offline only. The registry never fetches data; callers supply records parsed from
approved, provenance-tagged sources. Six eligibility flags are kept separate so
that discovery eligibility can never imply trading eligibility:

``LISTED_ACTIVE`` -> ``MARKET_DATA_COVERAGE`` -> ``SUFFICIENT_HISTORY`` ->
``STRATEGY_ELIGIBLE``; and independently ``BROKER_MAPPED`` ->
``BROKER_EXECUTION_ELIGIBLE``.

Survivorship control: a historical universe for date D only contains records
whose listing interval is *known* to cover D. Records built from a current
symbol-directory snapshot carry ``history_basis="SNAPSHOT"`` and are refused for
any date before their snapshot date.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any, Iterable, Literal, Sequence

SCHEMA_VERSION = "sd065.v1"

AssetType = Literal["COMMON_STOCK", "ETF", "FX_PAIR"]
HistoryBasis = Literal["POINT_IN_TIME", "SNAPSHOT"]
ActionKind = Literal[
    "SPLIT", "REVERSE_SPLIT", "MERGER", "SPINOFF", "SYMBOL_CHANGE", "SUSPENSION", "DELISTING"
]
ASSET_TYPES: frozenset[str] = frozenset({"COMMON_STOCK", "ETF", "FX_PAIR"})
ACTION_KINDS: frozenset[str] = frozenset(
    {"SPLIT", "REVERSE_SPLIT", "MERGER", "SPINOFF", "SYMBOL_CHANGE", "SUSPENSION", "DELISTING"}
)
# Cryptocurrencies are excluded by owner directive; these markers are refused outright.
_CRYPTO_PATTERN = re.compile(
    r"\b(CRYPTO\w*|BITCOIN|ETHEREUM|ETHER|SOLANA|BLOCKCHAIN|DOGECOIN|LITECOIN|BTC|ETH|XRP|SOL)\b"
)
BROKER_ENVIRONMENTS: frozenset[str] = frozenset({"DEMO", "PAPER"})
# Price quotation units. GBX = pence sterling (1/100 GBP); never confused with GBP.
QUOTE_UNITS: frozenset[str] = frozenset({"USD", "GBP", "GBX", "EUR"})
QUOTE_UNIT_CURRENCY: dict[str, str] = {"USD": "USD", "GBP": "GBP", "GBX": "GBP", "EUR": "EUR"}
# Optional identity fields: omitted from the canonical JSON when unset, so registries
# written before SD-090 keep their digests.
_OPTIONAL_IDENTITY_FIELDS = ("isin", "quote_unit")
_ISIN_PATTERN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")


def isin_is_valid(isin: str) -> bool:
    """ISO 6166 format and Luhn check digit (letters expand to two digits, A=10)."""
    if not _ISIN_PATTERN.match(isin):
        return False
    digits = "".join(str(int(ch, 36)) for ch in isin[:-1])
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 0:  # rightmost payload digit is doubled (check digit excluded)
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return (10 - total % 10) % 10 == int(isin[-1])

FLAGS = (
    "LISTED_ACTIVE",
    "MARKET_DATA_COVERAGE",
    "SUFFICIENT_HISTORY",
    "STRATEGY_ELIGIBLE",
    "BROKER_MAPPED",
    "BROKER_EXECUTION_ELIGIBLE",
)


class UniverseError(ValueError):
    pass


@dataclass(frozen=True)
class MarketDefinition:
    """Design-time market phase. Execution is never enabled by this table."""

    market_id: str
    phase: int
    country: str
    exchanges: tuple[str, ...]
    currencies: tuple[str, ...]
    discovery_enabled: bool
    execution_enabled: bool = False
    note: str = ""


MARKETS: dict[str, MarketDefinition] = {
    "US": MarketDefinition(
        "US", 1, "US", ("NYSE", "NASDAQ", "NYSE_ARCA", "NYSE_AMERICAN", "CBOE_BZX"), ("USD",),
        discovery_enabled=True,
        note="Phase 1. Execution still requires a verified broker mapping and a signed policy.",
    ),
    "UK": MarketDefinition(
        "UK", 2, "GB", ("LSE",), ("GBP", "USD", "EUR"), discovery_enabled=True,
        note=(
            "Phase 2 research/simulation (owner directive 2026-10-23, SD-088). Records need an "
            "explicit quote unit (GBX pence vs GBP pounds). UK broker execution needs separate "
            "owner approval; the MSFT pilot authorization never extends to UK instruments."
        ),
    ),
    "EU": MarketDefinition(
        "EU", 3, "EU", ("XETRA", "EURONEXT_PARIS", "EURONEXT_AMSTERDAM"), ("EUR",),
        discovery_enabled=False, note="Phase 3 design only.",
    ),
    "FX": MarketDefinition(
        "FX", 3, "XX", ("OTC_FX",), ("USD", "EUR", "GBP", "JPY", "CHF", "AUD", "CAD"),
        discovery_enabled=False, note="Phase 3 design only; major pairs.",
    ),
}
EXCHANGE_MARKET: dict[str, str] = {
    exchange: market.market_id for market in MARKETS.values() for exchange in market.exchanges
}


@dataclass(frozen=True)
class TickerInterval:
    ticker: str
    exchange: str
    start: date
    end: date | None = None  # inclusive; None = still current

    def covers(self, day: date) -> bool:
        return self.start <= day and (self.end is None or day <= self.end)


@dataclass(frozen=True)
class IndexMembership:
    index_id: str
    start: date
    end: date | None
    source: str

    def covers(self, day: date) -> bool:
        return self.start <= day and (self.end is None or day <= self.end)


@dataclass(frozen=True)
class CorporateAction:
    kind: str
    effective: date
    detail: str
    source: str


@dataclass(frozen=True)
class SourceCoverage:
    source_id: str
    granularity: str  # e.g. "1D", "5M"
    first_date: date
    last_date: date
    sessions: int
    provenance: str


@dataclass(frozen=True)
class BrokerMapping:
    broker: str
    environment: str
    broker_instrument_id: str
    verified_at: datetime | None
    verification_source: str
    execution_eligible: bool = False

    @property
    def verified(self) -> bool:
        return self.verified_at is not None and bool(self.verification_source.strip())


@dataclass(frozen=True)
class InstrumentRecord:
    canonical_id: str
    name: str
    country: str
    asset_type: str
    currency: str
    tickers: tuple[TickerInterval, ...]
    history_basis: str
    provenance: str
    listing_date: date | None = None
    delisting_date: date | None = None
    snapshot_date: date | None = None
    memberships: tuple[IndexMembership, ...] = ()
    actions: tuple[CorporateAction, ...] = ()
    coverage: tuple[SourceCoverage, ...] = ()
    broker_mappings: tuple[BrokerMapping, ...] = ()
    suspensions: tuple[tuple[date, date | None], ...] = ()
    exclusion_reasons: tuple[str, ...] = ()
    last_verified_at: datetime | None = None
    isin: str | None = None
    quote_unit: str | None = None  # unit the listing's prices are quoted in (e.g. GBX)

    def ticker_on(self, day: date) -> TickerInterval | None:
        matches = [interval for interval in self.tickers if interval.covers(day)]
        return matches[0] if len(matches) == 1 else None

    def listed_on(self, day: date) -> bool:
        """True only when the listing interval is *known* to cover ``day``."""
        if self.history_basis == "SNAPSHOT":
            return self.snapshot_date is not None and day >= self.snapshot_date and (
                self.delisting_date is None or day <= self.delisting_date
            )
        if self.listing_date is None or day < self.listing_date:
            return False
        return self.delisting_date is None or day <= self.delisting_date

    def suspended_on(self, day: date) -> bool:
        return any(start <= day and (end is None or day <= end) for start, end in self.suspensions)

    @property
    def market_id(self) -> str:
        exchange = self.tickers[-1].exchange if self.tickers else ""
        return EXCHANGE_MARKET.get(exchange, "UNKNOWN")


@dataclass(frozen=True)
class EligibilityReport:
    canonical_id: str
    as_of: date
    flags: dict[str, bool]
    reasons: tuple[str, ...]

    @property
    def discovery_eligible(self) -> bool:
        return self.flags["LISTED_ACTIVE"] and self.flags["MARKET_DATA_COVERAGE"]

    @property
    def strategy_eligible(self) -> bool:
        return self.flags["STRATEGY_ELIGIBLE"]

    @property
    def execution_eligible(self) -> bool:
        return self.flags["BROKER_EXECUTION_ELIGIBLE"]


def _validate_record(record: InstrumentRecord) -> None:
    cid = record.canonical_id
    if not cid.strip() or cid != cid.strip():
        raise UniverseError("canonical_id is required")
    tickers = " ".join(t.ticker for t in record.tickers)
    text = f"{record.canonical_id} {record.name} {record.asset_type} {tickers}".upper()
    if _CRYPTO_PATTERN.search(text.replace(":", " ")):
        raise UniverseError(f"{cid}: cryptocurrencies are excluded from the universe")
    if record.asset_type not in ASSET_TYPES:
        raise UniverseError(f"{cid}: unsupported asset type {record.asset_type!r}")
    if not record.currency or len(record.currency) != 3 or not record.currency.isupper():
        raise UniverseError(f"{cid}: invalid trading currency")
    if not record.provenance.strip():
        raise UniverseError(f"{cid}: provenance is required")
    if not record.tickers:
        raise UniverseError(f"{cid}: at least one ticker interval is required")
    if record.history_basis not in ("POINT_IN_TIME", "SNAPSHOT"):
        raise UniverseError(f"{cid}: invalid history basis")
    if record.history_basis == "SNAPSHOT" and record.snapshot_date is None:
        raise UniverseError(f"{cid}: snapshot records require snapshot_date")
    if record.history_basis == "POINT_IN_TIME" and record.listing_date is None:
        raise UniverseError(f"{cid}: point-in-time records require a listing date")
    if record.listing_date and record.delisting_date and record.delisting_date < record.listing_date:
        raise UniverseError(f"{cid}: delisting precedes listing")
    ordered = sorted(record.tickers, key=lambda interval: interval.start)
    for interval in ordered:
        if not interval.ticker.strip() or interval.ticker != interval.ticker.upper():
            raise UniverseError(f"{cid}: tickers must be non-empty upper case")
        if interval.exchange not in EXCHANGE_MARKET:
            raise UniverseError(f"{cid}: unknown exchange {interval.exchange!r}")
        if interval.end is not None and interval.end < interval.start:
            raise UniverseError(f"{cid}: ticker interval ends before it starts")
    for earlier, later in zip(ordered, ordered[1:]):
        if earlier.end is None or earlier.end >= later.start:
            raise UniverseError(f"{cid}: ticker intervals overlap")
    for membership in record.memberships:
        if membership.end is not None and membership.end < membership.start:
            raise UniverseError(f"{cid}: index membership ends before it starts")
        if not membership.source.strip():
            raise UniverseError(f"{cid}: index membership needs a source")
    for action in record.actions:
        if action.kind not in ACTION_KINDS:
            raise UniverseError(f"{cid}: unsupported corporate action {action.kind!r}")
    for cov in record.coverage:
        if cov.last_date < cov.first_date or cov.sessions < 0 or not cov.provenance.strip():
            raise UniverseError(f"{cid}: invalid data coverage entry")
    for mapping in record.broker_mappings:
        if mapping.environment not in BROKER_ENVIRONMENTS:
            raise UniverseError(f"{cid}: broker environment {mapping.environment!r} is refused")
        if mapping.execution_eligible and not mapping.verified:
            raise UniverseError(f"{cid}: execution eligibility requires a verified broker mapping")
    for start, end in record.suspensions:
        if end is not None and end < start:
            raise UniverseError(f"{cid}: suspension ends before it starts")
    if record.isin is not None and not isin_is_valid(record.isin):
        raise UniverseError(f"{cid}: invalid ISIN")
    if record.quote_unit is not None:
        if record.quote_unit not in QUOTE_UNITS:
            raise UniverseError(f"{cid}: unsupported quote unit {record.quote_unit!r}")
        if QUOTE_UNIT_CURRENCY[record.quote_unit] != record.currency:
            raise UniverseError(
                f"{cid}: quote unit {record.quote_unit} inconsistent with currency {record.currency}"
            )
    if record.market_id == "UK":
        if record.quote_unit is None:
            raise UniverseError(f"{cid}: LSE listings require an explicit quote unit (GBX or GBP)")
        if record.currency == "GBX":
            raise UniverseError(f"{cid}: GBX is a quote unit; the trading currency is GBP")


def evaluate_eligibility(
    record: InstrumentRecord,
    as_of: date,
    *,
    min_history_sessions: int = 252,
    data_source: str | None = None,
    broker: str = "ETORO",
    environment: str = "DEMO",
    max_coverage_gap_days: int = 4,
) -> EligibilityReport:
    """Separate eligibility flags. ``max_coverage_gap_days`` is in calendar days."""
    reasons: list[str] = []
    market = MARKETS.get(record.market_id)
    listed = record.listed_on(as_of) and not record.suspended_on(as_of)
    if not record.listed_on(as_of):
        reasons.append("NOT_KNOWN_LISTED_ON_DATE")
    if record.suspended_on(as_of):
        reasons.append("SUSPENDED")
    if record.ticker_on(as_of) is None:
        listed = False
        reasons.append("NO_UNIQUE_TICKER_ON_DATE")
    if market is None or not market.discovery_enabled:
        listed = False
        reasons.append("MARKET_NOT_ENABLED_FOR_DISCOVERY")
    candidates = [
        cov for cov in record.coverage
        if (data_source is None or cov.source_id == data_source) and cov.first_date <= as_of
    ]
    # A coverage record that extends past as_of counts sessions from the future; it must be
    # supplied point-in-time by the caller, so it is refused rather than pro-rated.
    coverage = [cov for cov in candidates if cov.last_date <= as_of]
    if len(coverage) < len(candidates):
        reasons.append("COVERAGE_RECORD_POSTDATES_AS_OF")
    has_coverage = any(
        (as_of - cov.last_date).days <= max_coverage_gap_days for cov in coverage
    )
    if not has_coverage:
        reasons.append("NO_CURRENT_MARKET_DATA_COVERAGE")
    sessions = max((cov.sessions for cov in coverage), default=0)
    sufficient = has_coverage and sessions >= min_history_sessions
    if has_coverage and not sufficient:
        reasons.append("INSUFFICIENT_HISTORY")
    excluded = bool(record.exclusion_reasons)
    reasons.extend(f"EXCLUDED:{reason}" for reason in record.exclusion_reasons)
    strategy = listed and has_coverage and sufficient and not excluded
    mapping = next(
        (m for m in record.broker_mappings if m.broker == broker and m.environment == environment), None
    )
    mapped = mapping is not None and mapping.verified
    if mapping is None:
        reasons.append("NO_BROKER_MAPPING")
    elif not mapping.verified:
        reasons.append("BROKER_MAPPING_UNVERIFIED")
    execution = strategy and mapped and mapping is not None and mapping.execution_eligible
    if mapped and mapping is not None and not mapping.execution_eligible:
        reasons.append("BROKER_EXECUTION_NOT_VERIFIED")
    flags = {
        "LISTED_ACTIVE": listed,
        "MARKET_DATA_COVERAGE": has_coverage,
        "SUFFICIENT_HISTORY": sufficient,
        "STRATEGY_ELIGIBLE": strategy,
        "BROKER_MAPPED": mapped,
        "BROKER_EXECUTION_ELIGIBLE": execution,
    }
    return EligibilityReport(record.canonical_id, as_of, flags, tuple(reasons))


@dataclass(frozen=True)
class UniverseSlice:
    as_of: date
    members: tuple[InstrumentRecord, ...]
    refused_snapshot_records: int
    survivorship_risk: bool
    index_id: str | None


@dataclass(frozen=True)
class RegistryDiff:
    added: tuple[str, ...]
    removed: tuple[str, ...]
    changed: tuple[str, ...]
    history_rewrites: tuple[str, ...]


@dataclass(frozen=True)
class MarketUniverseRegistry:
    version: int
    created_at: datetime
    source_note: str
    records: tuple[InstrumentRecord, ...]
    _by_id: dict[str, InstrumentRecord] = field(default_factory=dict, compare=False, repr=False)

    def __post_init__(self) -> None:
        if self.version < 1:
            raise UniverseError("registry version must be positive")
        if self.created_at.tzinfo is None:
            raise UniverseError("registry timestamps must be timezone-aware")
        index: dict[str, InstrumentRecord] = {}
        for record in self.records:
            _validate_record(record)
            if record.canonical_id in index:
                raise UniverseError(f"duplicate canonical id {record.canonical_id}")
            index[record.canonical_id] = record
        _reject_ticker_collisions(self.records)
        object.__setattr__(self, "_by_id", index)

    @property
    def digest(self) -> str:
        header = f"{SCHEMA_VERSION}|{self.version}|{self.created_at.isoformat()}|{self.source_note}|"
        return hashlib.sha256((header + _canonical_json(self.records)).encode()).hexdigest()

    def get(self, canonical_id: str) -> InstrumentRecord:
        try:
            return self._by_id[canonical_id]
        except KeyError as exc:
            raise UniverseError(f"unknown instrument {canonical_id}") from exc

    def resolve(self, ticker: str, as_of: date, exchange: str | None = None) -> InstrumentRecord:
        """Resolve a ticker as it was on ``as_of``. Ambiguity fails closed."""
        ticker = ticker.strip().upper()
        found = [
            record for record in self.records
            for interval in record.tickers
            if interval.ticker == ticker and interval.covers(as_of)
            and (exchange is None or interval.exchange == exchange)
        ]
        if not found:
            raise UniverseError(f"ticker {ticker} not known on {as_of.isoformat()}")
        if len({record.canonical_id for record in found}) > 1:
            raise UniverseError(f"ticker {ticker} is ambiguous on {as_of.isoformat()}; give exchange")
        return found[0]

    def universe_as_of(
        self,
        as_of: date,
        *,
        index_id: str | None = None,
        asset_types: Iterable[str] = ("COMMON_STOCK", "ETF"),
        markets: Iterable[str] = ("US",),
    ) -> UniverseSlice:
        allowed_types = set(asset_types)
        allowed_markets = set(markets)
        members: list[InstrumentRecord] = []
        refused = 0
        for record in self.records:
            if record.asset_type not in allowed_types or record.market_id not in allowed_markets:
                continue
            if record.history_basis == "SNAPSHOT" and (
                record.snapshot_date is None or as_of < record.snapshot_date
            ):
                refused += 1
                continue
            if not record.listed_on(as_of) or record.ticker_on(as_of) is None:
                continue
            if index_id is not None and not any(
                m.index_id == index_id and m.covers(as_of) for m in record.memberships
            ):
                continue
            members.append(record)
        members.sort(key=lambda record: record.canonical_id)
        return UniverseSlice(as_of, tuple(members), refused, refused > 0, index_id)

    def refresh(
        self, records: Sequence[InstrumentRecord], *, created_at: datetime, source_note: str,
        allow_history_correction: bool = False,
    ) -> tuple["MarketUniverseRegistry", RegistryDiff]:
        """Create the next version. Silent rewrites of history are refused."""
        new_ids = {record.canonical_id: record for record in records}
        old_ids = self._by_id
        added = tuple(sorted(set(new_ids) - set(old_ids)))
        removed = tuple(sorted(set(old_ids) - set(new_ids)))
        changed: list[str] = []
        rewrites: list[str] = []
        for cid in sorted(set(new_ids) & set(old_ids)):
            old, new = old_ids[cid], new_ids[cid]
            if old == new:
                continue
            changed.append(cid)
            if _history_rewritten(old, new):
                rewrites.append(cid)
        if removed:
            # Instruments are never deleted; a delisting must be recorded as an end date.
            raise UniverseError(f"refresh would drop instruments without delisting: {removed[:5]}")
        if rewrites and not allow_history_correction:
            raise UniverseError(f"refresh rewrites recorded history: {tuple(rewrites[:5])}")
        registry = MarketUniverseRegistry(self.version + 1, created_at, source_note, tuple(records))
        return registry, RegistryDiff(added, removed, tuple(changed), tuple(rewrites))

    def refresh_from_snapshot(
        self, snapshot: Sequence[InstrumentRecord], *, snapshot_date: date, created_at: datetime,
        source_note: str,
    ) -> tuple["MarketUniverseRegistry", RegistryDiff]:
        """Apply a newer directory snapshot without survivorship bias.

        Existing records keep their history. Open SNAPSHOT records missing from the new
        snapshot are closed (last known listed day = the day before ``snapshot_date``);
        the exact delisting day is unknown, so the record is also tagged for review.
        """
        if any(r.history_basis != "SNAPSHOT" or r.snapshot_date != snapshot_date
               for r in snapshot):
            raise UniverseError("snapshot records must carry the new snapshot date")
        latest = max((r.snapshot_date for r in self.records if r.snapshot_date), default=None)
        if latest is not None and snapshot_date <= latest:
            raise UniverseError("snapshot is not newer than the registry")
        incoming = {r.canonical_id: r for r in snapshot}
        last_listed = date.fromordinal(snapshot_date.toordinal() - 1)
        records: list[InstrumentRecord] = []
        for record in self.records:
            if record.canonical_id in incoming or record.delisting_date is not None                     or record.history_basis != "SNAPSHOT":
                records.append(record)
                continue
            tickers = tuple(
                TickerInterval(t.ticker, t.exchange, t.start, last_listed) if t.end is None else t
                for t in record.tickers
            )
            records.append(InstrumentRecord(**{
                **{f: getattr(record, f) for f in record.__dataclass_fields__},
                "tickers": tickers, "delisting_date": last_listed,
                "exclusion_reasons": record.exclusion_reasons
                + (f"ABSENT_FROM_SNAPSHOT_{snapshot_date.isoformat()}",),
            }))
        known = {r.canonical_id for r in self.records}
        records.extend(r for cid, r in sorted(incoming.items()) if cid not in known)
        return self.refresh(records, created_at=created_at, source_note=source_note)

    def to_json(self) -> str:
        payload = {
            "schema": SCHEMA_VERSION,
            "version": self.version,
            "created_at": self.created_at.isoformat(),
            "source_note": self.source_note,
            "digest": self.digest,
            "records": json.loads(_canonical_json(self.records)),
        }
        return json.dumps(payload, sort_keys=True, indent=1)

    @classmethod
    def from_json(cls, text: str) -> "MarketUniverseRegistry":
        payload = json.loads(text)
        if payload.get("schema") != SCHEMA_VERSION:
            raise UniverseError("unsupported registry schema")
        records = tuple(_record_from_dict(item) for item in payload["records"])
        registry = cls(
            int(payload["version"]), datetime.fromisoformat(payload["created_at"]),
            str(payload["source_note"]), records,
        )
        if registry.digest != payload.get("digest"):
            raise UniverseError("registry digest mismatch; file was altered")
        return registry


def _history_rewritten(old: InstrumentRecord, new: InstrumentRecord) -> bool:
    """Only additive changes and closing an open interval are ordinary refreshes."""
    if (old.listing_date != new.listing_date or old.snapshot_date != new.snapshot_date
            or old.history_basis != new.history_basis):
        return True
    if not set(old.exclusion_reasons) <= set(new.exclusion_reasons):
        return True
    # Identity: an ISIN or quote unit may be added once, never silently changed.
    for name in _OPTIONAL_IDENTITY_FIELDS:
        before = getattr(old, name)
        if before is not None and before != getattr(new, name):
            return True
    if not set(old.broker_mappings) <= set(new.broker_mappings):
        return True
    for start, end in set(old.suspensions) - set(new.suspensions):
        if end is not None or not any(s == start and e is not None for s, e in new.suspensions):
            return True
    for cov in set(old.coverage) - set(new.coverage):
        if not any(
            c.source_id == cov.source_id and c.granularity == cov.granularity
            and c.first_date == cov.first_date and c.last_date >= cov.last_date
            and c.sessions >= cov.sessions
            for c in new.coverage
        ):
            return True
    if old.delisting_date is not None and old.delisting_date != new.delisting_date:
        return True
    for interval in set(old.tickers) - set(new.tickers):
        if interval.end is not None or not any(
            t.ticker == interval.ticker and t.exchange == interval.exchange
            and t.start == interval.start and t.end is not None
            for t in new.tickers
        ):
            return True
    for membership in set(old.memberships) - set(new.memberships):
        if membership.end is not None or not any(
            m.index_id == membership.index_id and m.start == membership.start and m.end is not None
            for m in new.memberships
        ):
            return True
    return not set(old.actions) <= set(new.actions)


def _reject_ticker_collisions(records: Sequence[InstrumentRecord]) -> None:
    seen: dict[tuple[str, str], list[tuple[str, TickerInterval]]] = {}
    for record in records:
        for interval in record.tickers:
            seen.setdefault((interval.ticker, interval.exchange), []).append(
                (record.canonical_id, interval)
            )
    for (ticker, exchange), items in seen.items():
        for i, (cid_a, a) in enumerate(items):
            for cid_b, b in items[i + 1:]:
                if cid_a == cid_b:
                    continue
                a_end = a.end or date.max
                b_end = b.end or date.max
                if a.start <= b_end and b.start <= a_end:
                    raise UniverseError(
                        f"ticker {ticker} on {exchange} assigned to {cid_a} and {cid_b} at once"
                    )


def _default(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(type(value).__name__)


def _record_dict(record: InstrumentRecord) -> dict[str, Any]:
    data = asdict(record)
    for name in _OPTIONAL_IDENTITY_FIELDS:
        if data.get(name) is None:
            data.pop(name, None)
    return data


def _canonical_json(records: Sequence[InstrumentRecord]) -> str:
    return json.dumps([_record_dict(r) for r in records], sort_keys=True, default=_default,
                      separators=(",", ":"))


def _d(value: Any) -> date | None:
    return None if value is None else date.fromisoformat(value)


def _dt(value: Any) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value)


def _record_from_dict(item: dict[str, Any]) -> InstrumentRecord:
    return InstrumentRecord(
        canonical_id=item["canonical_id"], name=item["name"], country=item["country"],
        asset_type=item["asset_type"], currency=item["currency"],
        tickers=tuple(
            TickerInterval(t["ticker"], t["exchange"], date.fromisoformat(t["start"]), _d(t["end"]))
            for t in item["tickers"]
        ),
        history_basis=item["history_basis"], provenance=item["provenance"],
        listing_date=_d(item["listing_date"]), delisting_date=_d(item["delisting_date"]),
        snapshot_date=_d(item["snapshot_date"]),
        memberships=tuple(
            IndexMembership(m["index_id"], date.fromisoformat(m["start"]), _d(m["end"]), m["source"])
            for m in item["memberships"]
        ),
        actions=tuple(
            CorporateAction(a["kind"], date.fromisoformat(a["effective"]), a["detail"], a["source"])
            for a in item["actions"]
        ),
        coverage=tuple(
            SourceCoverage(c["source_id"], c["granularity"], date.fromisoformat(c["first_date"]),
                           date.fromisoformat(c["last_date"]), int(c["sessions"]), c["provenance"])
            for c in item["coverage"]
        ),
        broker_mappings=tuple(
            BrokerMapping(b["broker"], b["environment"], b["broker_instrument_id"],
                          _dt(b["verified_at"]), b["verification_source"], bool(b["execution_eligible"]))
            for b in item["broker_mappings"]
        ),
        suspensions=tuple((date.fromisoformat(s[0]), _d(s[1])) for s in item["suspensions"]),
        exclusion_reasons=tuple(item["exclusion_reasons"]),
        last_verified_at=_dt(item["last_verified_at"]),
        isin=item.get("isin"), quote_unit=item.get("quote_unit"),
    )


# --- Snapshot parsers for public symbol directories (offline; caller supplies text) ---

_NASDAQ_MARKET = {"Q": "NASDAQ", "G": "NASDAQ", "S": "NASDAQ"}
_OTHER_EXCHANGE = {"N": "NYSE", "A": "NYSE_AMERICAN", "P": "NYSE_ARCA", "Z": "CBOE_BZX"}
_NON_COMMON_PATTERN = re.compile(
    r"\bWARRANTS?\b|\bRIGHTS?\b|\bUNITS?\b|\bPREFERRED\b|\bPREFERENCE\b|\bNOTES?\s+DUE\b"
    r"|\bDEBENTURES?\b|\bETNS?\b|%|(?<!AMERICAN )(?<!GLOBAL )\bDEPOSITARY\s+SHARES?\b"
)


@dataclass(frozen=True)
class SnapshotParseReport:
    records: tuple[InstrumentRecord, ...]
    rejected: tuple[tuple[str, str], ...]  # (symbol, reason)
    file_creation_line: str | None


def parse_nasdaq_symbol_directory(
    text: str, *, kind: Literal["nasdaqlisted", "otherlisted"], snapshot_date: date,
    provenance: str, require_footer: bool = True,
) -> SnapshotParseReport:
    """Parse Nasdaq Trader ``nasdaqlisted.txt`` / ``otherlisted.txt`` text.

    Produces SNAPSHOT-basis records only: these files list *current* symbols and carry
    no listing dates, so they cannot support historical backtests on their own.
    Test issues, non-common securities and malformed rows are rejected with reasons.
    """
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        raise UniverseError("empty symbol directory")
    header = lines[0].split("|")
    expected_first = "Symbol" if kind == "nasdaqlisted" else "ACT Symbol"
    if header[0] != expected_first:
        raise UniverseError(f"unexpected {kind} header")
    col = {name: i for i, name in enumerate(header)}
    records: list[InstrumentRecord] = []
    rejected: list[tuple[str, str]] = []
    footer: str | None = None
    seen: set[str] = set()
    for line in lines[1:]:
        if line.startswith("File Creation Time"):
            footer = line.strip()
            continue
        parts = line.split("|")
        if len(parts) != len(header):
            rejected.append((parts[0] if parts else "", "MALFORMED_ROW"))
            continue
        symbol = parts[0].strip().upper()
        name = parts[col["Security Name"]].strip()
        if not symbol or not symbol.replace(".", "").replace("-", "").isalnum():
            rejected.append((symbol, "INVALID_SYMBOL"))
            continue
        if parts[col["Test Issue"]].strip() != "N":
            rejected.append((symbol, "TEST_ISSUE"))
            continue
        if kind == "nasdaqlisted":
            exchange = _NASDAQ_MARKET.get(parts[col["Market Category"]].strip())
            status = parts[col["Financial Status"]].strip()
            if status not in ("N", ""):
                rejected.append((symbol, f"FINANCIAL_STATUS_{status}"))
                continue
        else:
            exchange = _OTHER_EXCHANGE.get(parts[col["Exchange"]].strip())
        if exchange is None:
            rejected.append((symbol, "UNSUPPORTED_EXCHANGE"))
            continue
        is_etf = parts[col["ETF"]].strip() == "Y"
        if not is_etf and _NON_COMMON_PATTERN.search(name.upper()):
            rejected.append((symbol, "NOT_COMMON_STOCK"))
            continue
        if symbol in seen:
            rejected.append((symbol, "DUPLICATE_SYMBOL"))
            continue
        seen.add(symbol)
        records.append(InstrumentRecord(
            canonical_id=f"US:{symbol}", name=name, country="US",
            asset_type="ETF" if is_etf else "COMMON_STOCK", currency="USD",
            tickers=(TickerInterval(symbol, exchange, snapshot_date),),
            history_basis="SNAPSHOT", provenance=provenance, snapshot_date=snapshot_date,
        ))
    if footer is None and require_footer:
        raise UniverseError(f"{kind}: missing File Creation Time footer (truncated file?)")
    return SnapshotParseReport(tuple(records), tuple(rejected), footer)


def merge_snapshots(*reports: SnapshotParseReport) -> tuple[tuple[InstrumentRecord, ...], tuple[str, ...]]:
    """Merge directory snapshots; a symbol present in two files is excluded, not guessed."""
    by_id: dict[str, InstrumentRecord] = {}
    conflicts: set[str] = set()
    for report in reports:
        for record in report.records:
            if record.canonical_id in by_id:
                conflicts.add(record.canonical_id)
            by_id[record.canonical_id] = record
    merged = tuple(sorted(
        (r for cid, r in by_id.items() if cid not in conflicts), key=lambda r: r.canonical_id
    ))
    return merged, tuple(sorted(conflicts))
