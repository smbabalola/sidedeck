"""Test-only builder for an SD-098 manifest directory (synthetic bars, real-format files).

The ISINs are the candidates' real, check-digit-valid ISINs, used only as identities; every
price here is synthetic and exists only inside pytest temporary directories.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from sidedeck.application.sd089_exchange_calendar import XLON
from sidedeck.application.sd090_uk_market import LISTING_COLUMNS, MEMBERSHIP_COLUMNS
from sidedeck.application.sd098_uk_import import ACTION_COLUMNS, BAR_COLUMNS, MANIFEST_SCHEMA

NOW = datetime(2026, 10, 23, 18, 0, tzinfo=XLON.zone)          # after the 16:30 London close
LISTINGS = [("BP.", "GB0007980591", "BP p.l.c."), ("SHEL", "GB00BP6MXD84", "Shell plc"),
            ("HSBA", "GB0005405286", "HSBC Holdings plc")]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _csv(path: Path, header: tuple[str, ...], rows: list[tuple[str, ...]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(",".join(header) + "\n" + "".join(",".join(r) + "\n" for r in rows),
                    encoding="utf-8")


def sessions(now: datetime = NOW, count: int = 260) -> tuple[date, ...]:
    end = XLON.last_completed_session(now)
    return XLON.sessions_between(end - timedelta(days=int(count * 1.6)), end)[-count:]


def bars_rows(seed: int, days: tuple[date, ...], *, base: Decimal = Decimal("450")
              ) -> list[tuple[str, ...]]:
    rows, price = [], base + seed * 10
    for i, day in enumerate(days):
        drift = Decimal((i * 7 + seed * 3) % 11 - 5) / 10
        close = (price + drift).quantize(Decimal("0.01"))
        high, low = close + 2, close - 2
        rows.append((day.isoformat(), str(close), str(high), str(low), str(close),
                     str(1_000_000 + i * 1000)))
        price = close
    return rows


def build_uk_dir(root: Path, *, basis: str = "REAL_DATA", now: datetime = NOW,
                 count: int = 260, drop_last: int = 0, gap: bool = False,
                 split: bool = False, licence: str = "Owner-licensed test fixture; internal use",
                 tamper: str | None = None) -> Path:
    """Write manifest.json plus listings, FTSE membership, actions and GBX daily bars."""
    root.mkdir(parents=True, exist_ok=True)
    snap = XLON.last_completed_session(now)
    days = sessions(now, count)
    listing_rows = [(t, isin, name, "ORDINARY_SHARE", "GBX", "GBP", "2001-01-02", "",
                     "2001-01-02", "", "owner file", snap.isoformat())
                    for t, isin, name in LISTINGS]
    _csv(root / "listings.csv", LISTING_COLUMNS, listing_rows)
    _csv(root / "ftse.csv", MEMBERSHIP_COLUMNS,
         [("FTSE100", isin, snap.isoformat(), "", "SNAPSHOT", "owner constituents list")
          for _, isin, _ in LISTINGS])
    action_rows: list[tuple[str, ...]] = [("GB0007980591", days[-30].isoformat(), "DIVIDEND",
                                           "", "", "6.5", "GBX", "owner actions file")]
    if split:
        action_rows.append(("GB0005405286", days[-60].isoformat(), "SPLIT", "1", "2", "", "",
                            "owner actions file"))
    _csv(root / "actions.csv", ACTION_COLUMNS, action_rows)
    bar_entries = []
    for seed, (_, isin, _) in enumerate(LISTINGS):
        series_days = days[:len(days) - drop_last] if drop_last else days
        rows = bars_rows(seed, series_days)
        if gap and seed == 0:
            del rows[len(rows) // 2]
        if split and isin == "GB0005405286":                    # raw prices double before
            rows = [(r[0], *(str(Decimal(v) * 2) for v in r[1:5]), r[5]) if
                    date.fromisoformat(r[0]) < days[-60] else r for r in rows]
        rel = f"bars/{isin}.csv"
        _csv(root / rel, BAR_COLUMNS, rows)
        bar_entries.append({"isin": isin, "file": rel, "sha256": _sha(root / rel),
                            "source_id": "OWNER_LICENSED_EOD", "unit": "GBX",
                            "adjustment": "RAW",
                            "retrieved_at": (now - timedelta(hours=1)).isoformat()})
    manifest = {
        "schema": MANIFEST_SCHEMA, "data_basis": basis, "licence": licence,
        "source": "owner-supplied test files",
        "listings": {"file": "listings.csv", "sha256": _sha(root / "listings.csv")},
        "memberships": {"file": "ftse.csv", "sha256": _sha(root / "ftse.csv"),
                        "snapshot_date": snap.isoformat()},
        "corporate_actions": {"file": "actions.csv", "sha256": _sha(root / "actions.csv")},
        "bars": bar_entries,
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    if tamper is not None:
        target = root / tamper
        target.write_text(target.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    return root
