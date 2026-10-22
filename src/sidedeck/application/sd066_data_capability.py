"""SD-066 market-data capability matrix and provider request budgets (offline).

The matrix records what each known source can *honestly* provide. It never
upgrades delayed data to real time or a single venue to a consolidated tape.
``ProviderBudget`` reserves capacity *before* a request is sent, persists counts
in a caller-owned SQLite file, isolates failing providers with a circuit breaker
and only retries idempotent reads that did not fail on authorization.

Nothing here performs a network request or reads a credential.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

Delay = Literal["REALTIME", "DELAYED_15M", "END_OF_DAY", "SNAPSHOT", "UNKNOWN"]
RUNTIME_USABLE: frozenset[str] = frozenset({"APPROVED_PUBLIC"})
STATUSES: frozenset[str] = frozenset({
    "APPROVED_PUBLIC",              # public, policy-compliant, usable autonomously
    "OWNER_AUTHORIZATION_PER_RUN",  # each use needs a bounded owner authorization
    "AUTHORIZATION_EXHAUSTED",
    "NOT_APPROVED",
    "PENDING_POLICY_REVIEW",
})


class CapabilityError(ValueError):
    pass


@dataclass(frozen=True)
class SourceCapability:
    source_id: str
    description: str
    exchanges: tuple[str, ...]
    asset_types: tuple[str, ...]
    history_depth: str
    granularities: tuple[str, ...]
    delay: str
    consolidated: bool | None  # None = unknown; never assumed True
    corporate_actions: str
    usage_restrictions: str
    rate_limit_requests: int
    rate_limit_seconds: int
    cost: str
    status: str
    evidence: str


# Only facts already recorded in this repository's docs are encoded here.
CAPABILITY_MATRIX: tuple[SourceCapability, ...] = (
    SourceCapability(
        "SEC_EDGAR", "SEC EDGAR submissions/XBRL company facts", ("US",), ("COMMON_STOCK",),
        "issuer filing history", ("FILING",), "SNAPSHOT", None, "NOT_APPLICABLE",
        "public; identified User-Agent; fair-access throttling", 10, 1, "free",
        "APPROVED_PUBLIC", "docs/P5_SEC_EDGAR.md",
    ),
    SourceCapability(
        "NASDAQ_TRADER_SYMBOL_DIRECTORY", "nasdaqlisted.txt / otherlisted.txt symbol directory",
        ("NASDAQ", "NYSE", "NYSE_ARCA", "NYSE_AMERICAN", "CBOE_BZX"), ("COMMON_STOCK", "ETF"),
        "current snapshot only (no listing dates)", ("DIRECTORY",), "SNAPSHOT", None,
        "NOT_APPLICABLE", "public file; terms to be confirmed before automated refresh", 1, 60,
        "free", "PENDING_POLICY_REVIEW", "docs/SD065_MARKET_WIDE_ARCHITECTURE.md",
    ),
    SourceCapability(
        "ALPACA_SIP_DAILY", "Alpaca market data, SIP feed, daily bars", ("US",),
        ("COMMON_STOCK", "ETF"), "5 years retrieved for SPY/QQQ/MSFT only", ("1D",),
        "END_OF_DAY", True, "split-adjusted on request; dividends not corroborated",
        "authenticated; owner-authorized bounded runs only", 200, 60, "subscription-dependent",
        "AUTHORIZATION_EXHAUSTED", "docs/SD021_RESULTS.md",
    ),
    SourceCapability(
        "ALPACA_IEX", "Alpaca IEX feed", ("US",), ("COMMON_STOCK", "ETF"), "varies",
        ("1D", "1M"), "UNKNOWN", False, "provider-adjusted",
        "IEX venue only; not a consolidated close", 200, 60, "free tier",
        "NOT_APPROVED", "docs/P5_ALPACA_HISTORY.md",
    ),
    SourceCapability(
        "ETORO_DEMO_MARKET_DATA", "eToro public API instrument search / rates", ("US",),
        ("COMMON_STOCK", "ETF"), "candle entitlement NOT_VERIFIED", ("RATES",), "UNKNOWN", None,
        "UNKNOWN", "authenticated; per-request owner authorization", 60, 60, "free with account",
        "OWNER_AUTHORIZATION_PER_RUN", "docs/M2_ETORO_MARKET_DATA_ENDPOINT_MATRIX.md",
    ),
    SourceCapability(
        "TIINGO_EOD", "Tiingo end-of-day prices", ("US",), ("COMMON_STOCK", "ETF"), "decades",
        ("1D",), "END_OF_DAY", None, "adjusted and raw fields",
        "free tier personal internal use only; token use not approved", 50, 3600, "free tier",
        "NOT_APPROVED", "outer AGENTS.md Tiingo note",
    ),
    SourceCapability(
        "YAHOO_UNOFFICIAL", "Yahoo Finance unofficial endpoints", ("US",),
        ("COMMON_STOCK", "ETF"), "varies", ("1D",), "UNKNOWN", None, "UNKNOWN",
        "unofficial; rate-limited; terms unclear", 0, 60, "n/a", "NOT_APPROVED",
        "TODO.md SD-004",
    ),
    SourceCapability(
        "OWNER_CSV_IMPORT", "Owner-supplied licensed CSV files", ("US",),
        ("COMMON_STOCK", "ETF"), "as supplied", ("1D",), "END_OF_DAY", None,
        "must be declared per file", "licence declared by owner per file", 0, 1, "n/a",
        "APPROVED_PUBLIC", "docs/PROVENANCE.md",
    ),
)


def capability(source_id: str) -> SourceCapability:
    for cap in CAPABILITY_MATRIX:
        if cap.source_id == source_id:
            return cap
    raise CapabilityError(f"unknown data source {source_id}")


@dataclass(frozen=True)
class DataNeed:
    purpose: str
    granularity: str
    asset_type: str
    max_delay: str  # strictest acceptable delay
    requires_consolidated: bool = False


_DELAY_RANK = {"REALTIME": 0, "DELAYED_15M": 1, "END_OF_DAY": 2, "SNAPSHOT": 3, "UNKNOWN": 9}


@dataclass(frozen=True)
class SourceSelection:
    need: DataNeed
    usable: tuple[str, ...]
    refused: tuple[tuple[str, str], ...]

    @property
    def status(self) -> str:
        return "AVAILABLE" if self.usable else "BLOCKED_EXTERNAL"


def select_sources(need: DataNeed) -> SourceSelection:
    """Return autonomously usable sources for a need, with a reason for every refusal."""
    if need.max_delay not in _DELAY_RANK:
        raise CapabilityError(f"unknown delay class {need.max_delay}")
    usable: list[str] = []
    refused: list[tuple[str, str]] = []
    for cap in CAPABILITY_MATRIX:
        if need.granularity not in cap.granularities:
            refused.append((cap.source_id, "GRANULARITY_UNAVAILABLE"))
        elif need.asset_type not in cap.asset_types:
            refused.append((cap.source_id, "ASSET_TYPE_UNCOVERED"))
        elif _DELAY_RANK[cap.delay] > _DELAY_RANK[need.max_delay]:
            refused.append((cap.source_id, f"DELAY_{cap.delay}_EXCEEDS_{need.max_delay}"))
        elif need.requires_consolidated and cap.consolidated is not True:
            refused.append((cap.source_id, "NOT_VERIFIED_CONSOLIDATED"))
        elif cap.status not in RUNTIME_USABLE:
            refused.append((cap.source_id, f"STATUS_{cap.status}"))
        else:
            usable.append(cap.source_id)
    return SourceSelection(need, tuple(usable), tuple(refused))


TRACK_DATA_NEEDS: dict[str, DataNeed] = {
    "DAY": DataNeed("intraday scan/entry", "5M", "COMMON_STOCK", "DELAYED_15M",
                    requires_consolidated=True),
    "SWING": DataNeed("daily scan", "1D", "COMMON_STOCK", "END_OF_DAY"),
    "POSITION": DataNeed("daily + fundamentals", "1D", "COMMON_STOCK", "END_OF_DAY"),
}


# --- Provider budgets ------------------------------------------------------------

@dataclass(frozen=True)
class BudgetPolicy:
    provider: str
    max_per_window: int
    window_seconds: int
    max_total: int  # hard cap over the policy lifetime
    max_retries: int = 0
    breaker_failures: int = 3
    breaker_cooldown_seconds: int = 600

    def __post_init__(self) -> None:
        if self.max_per_window < 0 or self.window_seconds <= 0 or self.max_total < 0:
            raise CapabilityError("invalid budget limits")
        if self.max_retries < 0 or self.max_retries > 3:
            raise CapabilityError("retries must be between 0 and 3")
        if self.breaker_failures < 1 or self.breaker_cooldown_seconds <= 0:
            raise CapabilityError("invalid circuit-breaker settings")


@dataclass(frozen=True)
class BudgetDecision:
    allowed: bool
    reason: str
    reservation_id: int | None = None


RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class ProviderBudget:
    """Persistent reserve-before-send budget with a circuit breaker per provider.

    A non-zero budget for a source that is not ``APPROVED_PUBLIC`` is refused at
    construction: authenticated or paid sources need a separate owner authorization
    object, which this class does not accept.
    """

    def __init__(self, path: Path, policy: BudgetPolicy) -> None:
        cap = capability(policy.provider)
        if cap.status not in RUNTIME_USABLE and policy.max_total > 0:
            raise CapabilityError(
                f"{policy.provider} is {cap.status}; a budget needs owner authorization first"
            )
        # The policy may be stricter than the provider's documented limit, never looser.
        if policy.max_per_window * cap.rate_limit_seconds > (
            cap.rate_limit_requests * policy.window_seconds
        ):
            raise CapabilityError(
                f"{policy.provider} budget exceeds the documented rate limit "
                f"{cap.rate_limit_requests}/{cap.rate_limit_seconds}s"
            )
        self._path = path
        self.policy = policy
        with closing(self._conn()) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS reservations (id INTEGER PRIMARY KEY, provider TEXT,"
                " at REAL, attempt INTEGER, outcome TEXT)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS breaker (provider TEXT PRIMARY KEY, failures INTEGER,"
                " open_until REAL)"
            )

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path, isolation_level=None)

    def reserve(self, now: datetime, *, attempt: int = 0) -> BudgetDecision:
        if now.tzinfo is None:
            raise CapabilityError("timezone-aware time required")
        p = self.policy
        if attempt > p.max_retries:
            return BudgetDecision(False, "RETRY_LIMIT")
        with closing(self._conn()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            reason = self._refusal(conn, now)
            if reason is not None:
                conn.execute("ROLLBACK")
                return BudgetDecision(False, reason)
            cur = conn.execute(
                "INSERT INTO reservations (provider, at, attempt, outcome) VALUES (?,?,?,?)",
                (p.provider, now.timestamp(), attempt, "RESERVED"),
            )
            conn.execute("COMMIT")
            return BudgetDecision(True, "RESERVED", cur.lastrowid)

    def _refusal(self, conn: sqlite3.Connection, now: datetime) -> str | None:
        p = self.policy
        row = conn.execute(
            "SELECT open_until FROM breaker WHERE provider=?", (p.provider,)
        ).fetchone()
        if row and row[0] is not None and row[0] > now.timestamp():
            return "CIRCUIT_OPEN"
        last = conn.execute(
            "SELECT MAX(at) FROM reservations WHERE provider=?", (p.provider,)
        ).fetchone()[0]
        if last is not None and last > now.timestamp():
            return "CLOCK_REGRESSION"
        total = conn.execute(
            "SELECT COUNT(*) FROM reservations WHERE provider=?", (p.provider,)
        ).fetchone()[0]
        if total >= p.max_total:
            return "TOTAL_BUDGET_EXHAUSTED"
        since = now.timestamp() - p.window_seconds
        recent = conn.execute(
            "SELECT COUNT(*) FROM reservations WHERE provider=? AND at>?", (p.provider, since)
        ).fetchone()[0]
        if recent >= p.max_per_window:
            return "RATE_LIMITED"
        return None

    def record_outcome(self, reservation_id: int, now: datetime, status_code: int | None) -> str:
        """Record the result; returns ``OK``, ``RETRY_ALLOWED`` or ``NO_RETRY``."""
        if now.tzinfo is None:
            raise CapabilityError("timezone-aware time required")
        p = self.policy
        ok = status_code is not None and 200 <= status_code < 300
        with closing(self._conn()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            updated = conn.execute(
                "UPDATE reservations SET outcome=? WHERE id=? AND provider=? AND outcome='RESERVED'",
                ("OK" if ok else f"FAIL_{status_code}", reservation_id, p.provider),
            ).rowcount
            if updated != 1:
                conn.execute("ROLLBACK")
                raise CapabilityError("unknown or already-recorded reservation")
            row = conn.execute("SELECT failures FROM breaker WHERE provider=?",
                               (p.provider,)).fetchone()
            failures = 0 if ok else (row[0] if row else 0) + 1
            open_until = None
            if failures >= p.breaker_failures:
                open_until = now.timestamp() + p.breaker_cooldown_seconds
            conn.execute(
                "INSERT INTO breaker (provider, failures, open_until) VALUES (?,?,?) "
                "ON CONFLICT(provider) DO UPDATE SET failures=excluded.failures,"
                " open_until=excluded.open_until",
                (p.provider, failures, open_until),
            )
            conn.execute("COMMIT")
        if ok:
            return "OK"
        # Never retry authorization failures, other client errors or unknown outcomes.
        return "RETRY_ALLOWED" if status_code in RETRYABLE_STATUS else "NO_RETRY"

    def usage(self) -> dict[str, int]:
        with closing(self._conn()) as conn:
            rows = conn.execute(
                "SELECT outcome, COUNT(*) FROM reservations WHERE provider=? GROUP BY outcome",
                (self.policy.provider,),
            ).fetchall()
        return {str(outcome): int(count) for outcome, count in rows}
