"""SD-098 importer for owner-supplied, licensed UK listings, constituents and daily prices.

Offline only: reads files the owner placed under an ignored directory (default
``data/uk``). Nothing is downloaded. Everything is driven by one manifest::

    data/uk/manifest.json   (schema "sidedeck.uk_import_manifest.v1")
    {
      "schema": "sidedeck.uk_import_manifest.v1",
      "data_basis": "REAL_DATA",
      "licence": "<licence / permitted-use statement written by the owner>",
      "source": "<who supplied the data and how>",
      "listings": {"file": "listings.csv", "sha256": "<hex>"},
      "memberships": {"file": "ftse.csv", "sha256": "<hex>", "snapshot_date": "2026-10-22"},
      "corporate_actions": {"file": "actions.csv", "sha256": "<hex>"},
      "bars": [{"isin": "GB...", "file": "bars/GB....csv", "sha256": "<hex>",
                "source_id": "<provider id>", "unit": "GBX", "adjustment": "RAW",
                "retrieved_at": "2026-10-22T18:00:00+00:00"}]
    }

Safety and validation (each failure is reported with a reason, never repaired):

* paths must stay inside the data directory; symlinks, absolute paths and ``..`` are
  refused; each file is size-capped and must match its manifest SHA-256;
* strict CSV headers (``sidedeck.uk_listings.v1``, ``sidedeck.uk_index_membership.v1``,
  ``sidedeck.uk_corporate_actions.v1``, ``sidedeck.uk_daily_bars.v1``) and ``Decimal``
  parsing (no NaN/Infinity);
* the owner *declares* ``REAL_DATA``; SideDeck records it as owner-declared and refuses
  synthetic markers (``ZZ`` ISIN prefix) in such an import;
* every bar series declares its unit (GBX/GBp/GBP) and adjustment basis
  (``RAW`` or ``SPLIT_ADJUSTED``). For ``RAW`` series, declared splits and share
  consolidations are applied to earlier bars (price / factor, volume x factor);
  dividends are recorded but prices stay price-only (not total return);
* an unexplained day-over-day move beyond 45 % in a RAW series is flagged for review
  (a possible undeclared split); 50x moves still fail as a unit flip in SD-090.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sidedeck.application.sd014_strategy_engine import StrategyBar
from sidedeck.application.sd065_market_universe import (
    CorporateAction,
    InstrumentRecord,
    MarketUniverseRegistry,
    SourceCoverage,
    isin_is_valid,
)
from sidedeck.application.sd090_uk_market import (
    SeriesInput,
    UkMarketError,
    apply_index_memberships,
    normalize_unit_label,
    parse_uk_listings,
)

MANIFEST_SCHEMA = "sidedeck.uk_import_manifest.v1"
MAX_FILE_BYTES = 20 * 1024 * 1024
BAR_COLUMNS = ("date", "open", "high", "low", "close", "volume")
ACTION_COLUMNS = ("isin", "effective_date", "kind", "ratio_from", "ratio_to", "amount",
                  "currency", "source")
ACTION_KINDS = frozenset({"SPLIT", "CONSOLIDATION", "DIVIDEND"})
ADJUSTMENTS = frozenset({"RAW", "SPLIT_ADJUSTED"})
REVIEW_MOVE = Decimal("0.45")


class UkImportError(ValueError):
    pass


@dataclass(frozen=True)
class ShareAction:
    isin: str
    effective: date
    kind: str
    factor: Decimal          # new shares per old share (2 = 2-for-1 split, 0.1 = 1-for-10)
    amount: Decimal | None
    currency: str | None
    source: str


@dataclass
class UkImport:
    status: str
    data_basis: str
    registry: MarketUniverseRegistry | None = None
    series: dict[str, SeriesInput] = field(default_factory=dict)
    actions: tuple[ShareAction, ...] = ()
    rejected: list[tuple[str, str]] = field(default_factory=list)
    warnings: list[tuple[str, str]] = field(default_factory=list)
    files: dict[str, str] = field(default_factory=dict)   # relative path -> sha256

    def summary(self) -> dict[str, Any]:
        return {
            "status": self.status, "data_basis": self.data_basis,
            "data_basis_attestation": "OWNER_DECLARED" if self.data_basis == "REAL_DATA" else None,
            "instruments": 0 if self.registry is None else len(self.registry.records),
            "bar_series": len(self.series), "corporate_actions": len(self.actions),
            "rejected": [list(r) for r in self.rejected],
            "warnings": [list(w) for w in self.warnings], "files": dict(sorted(self.files.items())),
        }


def _safe_file(root: Path, rel: object) -> Path:
    if not isinstance(rel, str) or not rel or rel.startswith(("/", "\\")) or ".." in rel \
            or ":" in rel:
        raise UkImportError(f"UNSAFE_PATH:{rel!r}")
    path = root / rel
    if path.is_symlink() or not path.is_file():
        raise UkImportError(f"MISSING_OR_SYMLINK:{rel}")
    resolved, base = path.resolve(), root.resolve()
    if base not in resolved.parents:
        raise UkImportError(f"PATH_ESCAPES_DATA_DIR:{rel}")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise UkImportError(f"FILE_TOO_LARGE:{rel}")
    return path


def _read(root: Path, entry: object, files: dict[str, str]) -> str:
    if not isinstance(entry, dict):
        raise UkImportError("MANIFEST_ENTRY_NOT_OBJECT")
    path = _safe_file(root, entry.get("file"))
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != entry.get("sha256"):
        raise UkImportError(f"SHA256_MISMATCH:{entry.get('file')}")
    files[str(entry["file"])] = digest
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise UkImportError(f"NOT_UTF8:{entry.get('file')}") from exc


def _dec(text: str, name: str) -> Decimal:
    try:
        value = Decimal(text.strip())
    except (InvalidOperation, AttributeError) as exc:
        raise UkImportError(f"INVALID_NUMBER:{name}") from exc
    if not value.is_finite():
        raise UkImportError(f"NON_FINITE:{name}")
    return value


def parse_daily_bars(text: str) -> tuple[StrategyBar, ...]:
    reader = csv.DictReader(io.StringIO(text))
    if tuple(reader.fieldnames or ()) != BAR_COLUMNS:
        raise UkImportError(f"BAR_HEADER_EXPECTED:{','.join(BAR_COLUMNS)}")
    bars: list[StrategyBar] = []
    seen: set[date] = set()
    for line, row in enumerate(reader, start=2):
        if None in row or any(row.get(c) is None for c in BAR_COLUMNS):
            raise UkImportError(f"MALFORMED_BAR_ROW:{line}")
        try:
            day = date.fromisoformat(row["date"].strip())
        except ValueError as exc:
            raise UkImportError(f"INVALID_DATE:{line}") from exc
        if day in seen:
            raise UkImportError(f"DUPLICATE_DATE:{day}")
        seen.add(day)
        o, h, lo, c, v = (_dec(row[k], f"{k}@{line}") for k in BAR_COLUMNS[1:])
        if min(o, h, lo, c) <= 0 or v < 0:
            raise UkImportError(f"NON_POSITIVE_VALUE:{line}")
        if h < max(o, c) or lo > min(o, c):
            raise UkImportError(f"INCONSISTENT_OHLC:{line}")
        bars.append(StrategyBar(day, o, h, lo, c, v))
    if not bars:
        raise UkImportError("NO_BARS")
    return tuple(sorted(bars, key=lambda b: b.day))


def parse_corporate_actions(text: str) -> tuple[tuple[ShareAction, ...], list[tuple[str, str]]]:
    reader = csv.DictReader(io.StringIO(text))
    if tuple(reader.fieldnames or ()) != ACTION_COLUMNS:
        raise UkImportError(f"ACTION_HEADER_EXPECTED:{','.join(ACTION_COLUMNS)}")
    actions: list[ShareAction] = []
    rejected: list[tuple[str, str]] = []
    for line, row in enumerate(reader, start=2):
        key = f"action@{line}"
        try:
            if None in row or any(row.get(c) is None for c in ACTION_COLUMNS):
                raise UkImportError("MALFORMED_ROW")
            isin, kind = row["isin"].strip(), row["kind"].strip()
            if not isin_is_valid(isin):
                raise UkImportError("INVALID_ISIN")
            if kind not in ACTION_KINDS:
                raise UkImportError(f"UNSUPPORTED_ACTION:{kind}")
            if not row["source"].strip():
                raise UkImportError("MISSING_SOURCE")
            effective = date.fromisoformat(row["effective_date"].strip())
            if kind == "DIVIDEND":
                amount = _dec(row["amount"], "amount")
                normalize_unit_label(row["currency"].strip())
                if amount <= 0:
                    raise UkImportError("NON_POSITIVE_DIVIDEND")
                actions.append(ShareAction(isin, effective, kind, Decimal(1), amount,
                                           row["currency"].strip(), row["source"].strip()))
                continue
            old, new = _dec(row["ratio_from"], "ratio_from"), _dec(row["ratio_to"], "ratio_to")
            if old <= 0 or new <= 0 or old == new:
                raise UkImportError("INVALID_RATIO")
            if (kind == "SPLIT") != (new > old):
                raise UkImportError("RATIO_CONTRADICTS_KIND")
            actions.append(ShareAction(isin, effective, kind, new / old, None, None,
                                       row["source"].strip()))
        except (UkImportError, UkMarketError, ValueError) as exc:
            rejected.append((key, str(exc)))
    return tuple(actions), rejected


def adjust_for_share_actions(
    bars: tuple[StrategyBar, ...], actions: tuple[ShareAction, ...],
) -> tuple[StrategyBar, ...]:
    """Back-adjust RAW bars dated before each split/consolidation effective date."""
    out = list(bars)
    for action in sorted(actions, key=lambda a: a.effective):
        if action.kind == "DIVIDEND":
            continue
        f = action.factor
        out = [
            StrategyBar(b.day, b.open / f, b.high / f, b.low / f, b.close / f, b.volume * f)
            if b.day < action.effective else b
            for b in out
        ]
    return tuple(out)


def _review_moves(isin: str, bars: tuple[StrategyBar, ...]) -> list[tuple[str, str]]:
    flags: list[tuple[str, str]] = []
    for prev, cur in zip(bars, bars[1:]):
        move = cur.close / prev.close - 1
        if abs(move) > REVIEW_MOVE:
            flags.append((isin, f"REVIEW_LARGE_MOVE_{cur.day.isoformat()}_{move:.2%}"))
    return flags


def import_uk_directory(root: Path, *, now: datetime) -> UkImport:
    """Import ``root/manifest.json``. Missing manifest -> NO_GENUINE_UK_DATA."""
    if now.tzinfo is None:
        raise UkImportError("timezone-aware time required")
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        return UkImport("NO_GENUINE_UK_DATA", "UNAVAILABLE")
    files: dict[str, str] = {}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return UkImport("MANIFEST_INVALID", "UNAVAILABLE", rejected=[("manifest", "NOT_JSON")])
    result = UkImport("MANIFEST_INVALID", "UNAVAILABLE", files=files)
    try:
        if not isinstance(manifest, dict) or manifest.get("schema") != MANIFEST_SCHEMA:
            raise UkImportError("UNSUPPORTED_MANIFEST_SCHEMA")
        basis = manifest.get("data_basis")
        if basis not in ("REAL_DATA", "SYNTHETIC_FIXTURE"):
            raise UkImportError("UNKNOWN_DATA_BASIS")
        licence, source = manifest.get("licence"), manifest.get("source")
        if not isinstance(licence, str) or not licence.strip() or not isinstance(source, str) \
                or not source.strip():
            raise UkImportError("LICENCE_AND_SOURCE_REQUIRED")
        note = f"{source.strip()} | licence: {licence.strip()}"
        listings = parse_uk_listings(_read(root, manifest.get("listings"), files),
                                     licence_note=note)
        result.rejected.extend(listings.rejected)
        records = list(listings.records)
        if basis == "REAL_DATA":
            synthetic = [r for r in records if (r.isin or "").startswith("ZZ")]
            for r in synthetic:
                result.rejected.append((r.isin or r.canonical_id, "SYNTHETIC_ISIN_IN_REAL_IMPORT"))
            records = [r for r in records if r not in synthetic]
        if manifest.get("memberships") is not None:
            entry = manifest["memberships"]
            snap = date.fromisoformat(str(entry.get("snapshot_date")))
            with_members, rej = apply_index_memberships(
                records, _read(root, entry, files), licence_note=note, snapshot_date=snap)
            records = list(with_members)
            result.rejected.extend(rej)
        actions: tuple[ShareAction, ...] = ()
        if manifest.get("corporate_actions") is not None:
            actions, action_rej = parse_corporate_actions(
                _read(root, manifest["corporate_actions"], files))
            result.rejected.extend(action_rej)
        by_isin = {r.isin: r for r in records}
        known_actions = tuple(a for a in actions if a.isin in by_isin)
        for a in actions:
            if a.isin not in by_isin:
                result.rejected.append((a.isin, "ACTION_FOR_UNKNOWN_ISIN"))
        series: dict[str, SeriesInput] = {}
        updated: dict[str, InstrumentRecord] = {}
        for entry in manifest.get("bars") or []:
            isin = entry.get("isin") if isinstance(entry, dict) else None
            try:
                if isin not in by_isin:
                    raise UkImportError("BARS_FOR_UNKNOWN_ISIN")
                record = by_isin[isin]
                if record.canonical_id in series:
                    raise UkImportError("DUPLICATE_SERIES")
                if entry.get("adjustment") not in ADJUSTMENTS:
                    raise UkImportError("ADJUSTMENT_BASIS_REQUIRED")
                unit_label = str(entry.get("unit"))
                normalize_unit_label(unit_label)
                retrieved = datetime.fromisoformat(str(entry.get("retrieved_at")))
                if retrieved.tzinfo is None or retrieved > now:
                    raise UkImportError("INVALID_RETRIEVED_AT")
                source_id = entry.get("source_id")
                if not isinstance(source_id, str) or not source_id.strip():
                    raise UkImportError("SOURCE_ID_REQUIRED")
                bars = parse_daily_bars(_read(root, entry, files))
                mine = tuple(a for a in known_actions if a.isin == isin)
                if entry["adjustment"] == "RAW":
                    bars = adjust_for_share_actions(bars, mine)
                    result.warnings.extend(_review_moves(str(isin), bars))
                digest = files[str(entry["file"])]
                provenance = (f"{source_id} | {entry['adjustment']} | price-only (dividends not "
                              f"reinvested) | file sha256={digest} | {note}")
                series[record.canonical_id] = SeriesInput(
                    record.canonical_id, source_id, unit_label, basis, provenance,
                    retrieved.astimezone(UTC), bars)
                cov = SourceCoverage(source_id, "1D", bars[0].day, bars[-1].day, len(bars),
                                     provenance)
                ca = tuple(
                    CorporateAction("SPLIT" if a.kind == "SPLIT" else "REVERSE_SPLIT",
                                    a.effective, f"factor {a.factor}", a.source)
                    for a in mine if a.kind != "DIVIDEND"
                )
                updated[record.canonical_id] = replace(
                    record, coverage=record.coverage + (cov,), actions=record.actions + ca)
            except (UkImportError, UkMarketError, ValueError, KeyError, TypeError) as exc:
                result.rejected.append((str(isin), str(exc)))
        final = tuple(updated.get(r.canonical_id, r) for r in records)
        result.registry = MarketUniverseRegistry(1, now, f"SD-098 import: {note}"[:500], final)
        result.series = series
        result.actions = known_actions
        result.data_basis = basis
        if final and series:
            result.status = "IMPORTED"
        elif final:
            result.status = "IMPORTED_NO_PRICE_DATA"
        else:
            result.status = "NO_VALID_RECORDS"
    except (UkImportError, UkMarketError, ValueError, KeyError, TypeError) as exc:
        result.rejected.append(("manifest", str(exc)))
        result.status = "MANIFEST_INVALID"
    return result
