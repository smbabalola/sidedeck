"""Pinned upstream identity, per-script SHA-256 and the capability matrix of the 11 skills.

The installed Claude Code plugin is preferred when it verifies; otherwise the vendored copy in
``third_party/day-trader-skill`` (same pinned bytes) is used. A copy whose scripts differ from
the pinned hashes is never run.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

UPSTREAM = {
    "name": "day-trader-skill", "version": "2.0.0",
    "commit": "3d0f4ef6986f4984b7c6bd46f7ff4f87744c3abd", "commit_date": "2026-10-20",
    "author": "Jake Schincariol", "license": "MIT",
    "repository": "https://github.com/Jakeschincariol/day-trader-skill",
}
SOURCE_VERSION = f"{UPSTREAM['version']}+{UPSTREAM['commit'][:8]}"
MODULE_BOOK = "DAY_TRADER_SKILL"
SCRIPT_SHA256 = {
    "trader-alerts/alerts.py": "4b22d5ef4e26e03d6f8c356a1e2e2dd4aee682a3b05abb5f456a9e1370d4a127",
    "trader-analyst/facts.py": "5f495a8d7c5f5686525e6a7eb62ae7c4151a1d5077daf18cad421e6d7b779704",
    "trader-broker/ticket.py": "a06ff7b1511ff397156478874efb3e5e90cad59d20397eaade6f99e8d8b6d317",
    "trader-budget/size.py": "547b65b60d097086884e2454750fa4830ee7464eae7ea5126b631cf0dff30b37",
    "trader-entry/entry.py": "40bfffb5b7a77494767f70a2fa14a37ed59af5ef75352e2bd1ab7aa45d16550a",
    "trader-exit/exit.py": "3e4083e754cdef0b53ce4c84953d695c834a419cc8a0f95b13d80abbbd46c4ec",
    "trader-news/news.py": "e377784802b00159ace6a5f9caa5deaf48cb2d96312158532ce5818726783405",
    "trader-pelosi/ptr.py": "6d10c786d9d5a1c7480b03e664f7a0126d302be58155af2779ec637c0c954c88",
    "trader-risk/check.py": "e29c6c2b00b8408ac5c4c7306af1432e1ba59b5287c920a21ac48fda4b15695e",
    "trader-scanner/scan.py": "86aacc71321712bd68b39190127c9164a14f727449c868f60a5ced10edd1d839",
    "trader-timemachine/timemachine.py":
        "3db5e7da25e421815f48caaa8bc52632a26120e5b124181a9a9358f6fd4a12f1",
}
LICENSE_SHA256 = "9f65c2af3935669d28c1afb82da45e5da609c590a636c233866a4888e84f91f4"
VENDORED_ROOT = Path(__file__).resolve().parents[4] / "third_party" / "day-trader-skill"
PLUGIN_KEY = "day-trader-skill@day-trader-skill"


@dataclass(frozen=True)
class SkillSpec:
    name: str
    script: str
    hosts: tuple[str, ...]                 # what the script would contact online
    allowed: frozenset[str] | None         # permitted subcommands (None = no subcommands)
    needs_offline: bool                    # SideDeck always forces --offline
    claude_only: str                       # parts that need Claude (never used by SideDeck)
    role: str


SKILLS: dict[str, SkillSpec] = {s.name: s for s in (
    SkillSpec("trader-scanner", "trader-scanner/scan.py",
              ("query1/query2.finance.yahoo.com", "www.nasdaqtrader.com"),
              frozenset({"universe", "daily", "orb"}), True,
              "explaining hits in plain language", "find setups (ORB, daily)"),
    SkillSpec("trader-news", "trader-news/news.py",
              ("feeds.finance.yahoo.com", "query2.finance.yahoo.com", "www.sec.gov"),
              None, True, "summarising headlines", "headlines, 8-K filings, big moves"),
    SkillSpec("trader-entry", "trader-entry/entry.py", ("query2.finance.yahoo.com",),
              frozenset({"check", "watchlist"}), True,
              "talking the user through the trigger", "time the entry"),
    SkillSpec("trader-exit", "trader-exit/exit.py", (),
              frozenset({"plan", "show"}), False, "explaining the plan", "stop, target, flat-by"),
    SkillSpec("trader-timemachine", "trader-timemachine/timemachine.py",
              ("query2.finance.yahoo.com",), frozenset({"run"}), True,
              "interpreting the fan chart", "scenario replays (not a forecast)"),
    SkillSpec("trader-risk", "trader-risk/check.py", (), None, False,
              "explaining blocks", "skill-level rule check (advisory only in SideDeck)"),
    SkillSpec("trader-budget", "trader-budget/size.py", (), None, False,
              "discussing weights", "position sizing"),
    SkillSpec("trader-broker", "trader-broker/ticket.py", (), frozenset({"show"}), False,
              "placing orders through an MCP broker connector (REFUSED in SideDeck)",
              "render tickets only; approve/result/fill/flatten refused"),
    SkillSpec("trader-alerts", "trader-alerts/alerts.py",
              ("query2.finance.yahoo.com", "stooq.com"), frozenset({"clock", "check"}), True,
              "ringing the user", "market clock and price alerts"),
    SkillSpec("trader-analyst", "trader-analyst/facts.py", ("data.sec.gov", "www.sec.gov"),
              None, True, "writing the analyst note", "SEC company facts"),
    SkillSpec("trader-pelosi", "trader-pelosi/ptr.py", ("disclosures-clerk.house.gov",),
              frozenset({"index", "new", "parse"}), True,
              "reading PTR PDFs (needs pdftotext; refused)", "congressional trade disclosures"),
)}


@dataclass(frozen=True)
class Verification:
    root: Path | None
    source: str              # INSTALLED_PLUGIN | VENDORED | NONE
    status: str              # VERIFIED | MISSING | MISMATCH
    mismatched: tuple[str, ...] = ()
    checked: dict[str, str] = field(default_factory=dict)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(root: Path | None, source: str) -> Verification:
    if root is None or not root.is_dir():
        return Verification(None, source, "MISSING")
    bad, checked = [], {}
    for rel, pinned in {**SCRIPT_SHA256, "LICENSE": LICENSE_SHA256}.items():
        target = root / rel
        if not target.is_file() or target.is_symlink():
            bad.append(rel)
            continue
        digest = _sha(target)
        checked[rel] = digest
        if digest != pinned:
            bad.append(rel)
    return Verification(root, source, "MISMATCH" if bad else "VERIFIED", tuple(bad), checked)


def installed_root(home: Path | None = None) -> Path | None:
    record = (home or Path.home()) / ".claude" / "plugins" / "installed_plugins.json"
    try:
        entries = json.loads(record.read_text(encoding="utf-8")).get("plugins", {}).get(
            PLUGIN_KEY, [])
    except (OSError, ValueError, AttributeError):
        return None
    for entry in entries if isinstance(entries, list) else []:
        if isinstance(entry, dict) and entry.get("gitCommitSha") == UPSTREAM["commit"]:
            path = Path(str(entry.get("installPath", "")))
            if path.is_dir():
                return path
    return None


def resolve(home: Path | None = None) -> Verification:
    """Installed plugin if it verifies, else the vendored copy, else nothing runnable."""
    if os.environ.get("SIDEDECK_DAY_TRADER_FORCE_VENDORED") != "1":
        installed = verify(installed_root(home), "INSTALLED_PLUGIN")
        if installed.status == "VERIFIED":
            return installed
    return verify(VENDORED_ROOT, "VENDORED")
