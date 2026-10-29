"""SD-077 owner-signed, bounded data-acquisition authorizations (no network here).

A data request (public download or authenticated market-data GET) is allowed
only under a ``DataAuthorization`` that the owner signs with their SSH key in
the dedicated namespace ``sidedeck-data-authorization``. SideDeck never holds
or uses the private key; it verifies with ``ssh-keygen -Y verify`` through the
SD-045 verifier. The authorization pins provider, exact URLs, request cap,
retry cap and expiry. ``DataRequestLedger`` reserves every request *before* it
is sent, persists across restarts and refuses anything outside the scope.

Broker endpoints, order routes and paid services cannot be authorized here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qsl, urlsplit

NAMESPACE = "sidedeck-data-authorization"
SCHEMA = "sidedeck.data_authorization.v1"
MAX_LIFETIME = timedelta(days=7)
# Provider -> allowed HTTPS hosts. Trading/broker hosts are never listed.
PROVIDER_HOSTS: dict[str, frozenset[str]] = {
    "NASDAQ_TRADER_SYMBOL_DIRECTORY": frozenset({"www.nasdaqtrader.com"}),
    "ALPACA_SIP_DAILY": frozenset({"data.alpaca.markets"}),
    "ALPACA_SIP_INTRADAY": frozenset({"data.alpaca.markets"}),
    # SD-094A: public England & Wales bank-holiday feed (Open Government Licence v3.0).
    "GOV_UK_BANK_HOLIDAYS": frozenset({"www.gov.uk"}),
    "ETORO_DEMO_MARKET_DATA": frozenset({"public-api.etoro.com"}),
}
_FORBIDDEN_PATH_PARTS = ("/orders", "/positions", "/account", "/trading", "/v2/account")
_UNSAFE_PATH_TOKENS = ("%", "..", "//", ";", "\\")
# One fixed ledger for every data authorization: the cap cannot be reset by choosing a path.
DEFAULT_LEDGER = Path("data") / "data-authorization-ledger.sqlite3"


def _check_url(url: str, hosts: frozenset[str]) -> str:
    """Return the canonical path of a safe HTTPS URL on an allowed host, else refuse."""
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.netloc not in hosts or parts.fragment:
        raise AuthorizationRefused(f"URL not allowed: {url}")
    path = parts.path
    if not path.startswith("/") or any(tok in path for tok in _UNSAFE_PATH_TOKENS):
        raise AuthorizationRefused(f"unsafe URL path: {url}")
    if any(bad in path.lower() for bad in _FORBIDDEN_PATH_PARTS):
        raise AuthorizationRefused("broker/account/order paths are never authorized")
    return f"https://{parts.netloc}{path}"


class AuthorizationRefused(ValueError):
    pass


@dataclass(frozen=True)
class DataAuthorization:
    authorization_id: str
    provider: str
    purpose: str
    urls: tuple[str, ...]  # exact URL prefixes allowed (query strings may vary)
    max_requests: int
    max_retries: int
    credentials_required: bool
    issued_at: datetime
    expires_at: datetime
    owner_terms_reviewed: bool
    notes: str = ""
    schema: str = SCHEMA
    scope: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("authorization_id", "provider", "purpose", "notes", "schema"):
            if not isinstance(getattr(self, name), str):
                raise AuthorizationRefused(f"{name} must be a string")
        if not isinstance(self.scope, dict):
            raise AuthorizationRefused("scope must be an object")
        for name in ("max_requests", "max_retries"):
            if type(getattr(self, name)) is not int:
                raise AuthorizationRefused(f"{name} must be an integer")
        for name in ("credentials_required", "owner_terms_reviewed"):
            if type(getattr(self, name)) is not bool:
                raise AuthorizationRefused(f"{name} must be a boolean")
        if not isinstance(self.urls, tuple) or not all(isinstance(u, str) for u in self.urls):
            raise AuthorizationRefused("urls must be strings")
        if self.schema != SCHEMA:
            raise AuthorizationRefused("unsupported authorization schema")
        if not self.authorization_id.strip() or not self.purpose.strip():
            raise AuthorizationRefused("authorization id and purpose are required")
        if not all(c.isalnum() or c in "-_." for c in self.authorization_id):
            raise AuthorizationRefused("authorization id must be a simple identifier")
        hosts = PROVIDER_HOSTS.get(self.provider)
        if hosts is None:
            raise AuthorizationRefused(f"provider {self.provider} cannot be authorized here")
        if not self.urls:
            raise AuthorizationRefused("at least one URL is required")
        for url in self.urls:
            if urlsplit(url).query or _check_url(url, hosts) != url:
                raise AuthorizationRefused(f"URL not allowed for {self.provider}: {url}")
        if not 1 <= self.max_requests <= 200:
            raise AuthorizationRefused("max_requests must be 1-200")
        if not 0 <= self.max_retries <= 2:
            raise AuthorizationRefused("max_retries must be 0-2")
        if self.issued_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise AuthorizationRefused("timestamps must be timezone-aware")
        if not self.issued_at < self.expires_at <= self.issued_at + MAX_LIFETIME:
            raise AuthorizationRefused("authorization must expire within 7 days of issue")
        if not self.owner_terms_reviewed:
            raise AuthorizationRefused("owner must confirm the source terms were reviewed")
        if self.provider == "ALPACA_SIP_INTRADAY":
            keys = {"timeframe", "feed", "adjustment", "start", "end", "limit"}
            if set(self.scope) != keys or any(
                not isinstance(self.scope.get(key), str) for key in keys
            ):
                raise AuthorizationRefused("intraday query scope must pin all six fields")
            if (self.scope["timeframe"] != "5Min" or self.scope["feed"] != "sip"
                    or self.scope["adjustment"] != "split"
                    or self.scope["limit"] != "10000"
                    or not self.scope["start"] or not self.scope["end"]
                    or self.scope["start"] >= self.scope["end"]):
                raise AuthorizationRefused("intraday query scope is invalid")

    def canonical(self) -> str:
        data = asdict(self)
        data["issued_at"] = self.issued_at.astimezone(UTC).isoformat()
        data["expires_at"] = self.expires_at.astimezone(UTC).isoformat()
        return json.dumps(data, sort_keys=True, separators=(",", ":"))

    def allows_url(self, url: str) -> bool:
        """Match an exact authorized path or a documented instrument-ID template."""
        base = _check_url(url, PROVIDER_HOSTS[self.provider])
        if self.provider == "ALPACA_SIP_INTRADAY":
            pairs = parse_qsl(urlsplit(url).query, keep_blank_values=True)
            actual = dict(pairs)
            if len(pairs) != len(actual):
                return False
            token = actual.pop("page_token", None)
            if token is not None and (not token or len(token) > 512):
                return False
            if actual != self.scope:
                return False
        for authorized in self.urls:
            if "{instrumentId}" not in authorized:
                if base == authorized:
                    return True
                continue
            prefix, suffix = authorized.split("{instrumentId}", 1)
            if base.startswith(prefix) and base.endswith(suffix):
                middle = base[len(prefix):len(base) - len(suffix) if suffix else None]
                if middle.isdigit() and int(middle) > 0:
                    return True
        return False

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.canonical().encode()).hexdigest()

    @classmethod
    def from_json(cls, text: str) -> "DataAuthorization":
        try:
            data: dict[str, Any] = json.loads(text)
            data["urls"] = tuple(data["urls"])
            data["issued_at"] = datetime.fromisoformat(data["issued_at"])
            data["expires_at"] = datetime.fromisoformat(data["expires_at"])
            return cls(**data)
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            if isinstance(exc, AuthorizationRefused):
                raise
            raise AuthorizationRefused(f"malformed authorization: {exc}") from exc


Verifier = Callable[[str, str, str], bool]


def verify_authorization(
    auth: DataAuthorization, signature: str, *, verifier: Verifier, principal: str,
    now: datetime,
) -> DataAuthorization:
    """Return ``auth`` only if the owner signed its digest and it is currently valid."""
    if getattr(verifier, "namespace", None) != NAMESPACE:
        raise AuthorizationRefused(f"verifier must use namespace {NAMESPACE}")
    if now.tzinfo is None:
        raise AuthorizationRefused("timezone-aware time required")
    if not verifier(principal, auth.digest, signature):
        raise AuthorizationRefused("owner signature did not verify")
    if not auth.issued_at <= now < auth.expires_at:
        raise AuthorizationRefused("authorization is not currently valid")
    return auth


class DataRequestLedger:
    """Persistent reserve-before-send ledger bound to one authorization digest."""

    def __init__(self, path: Path, auth: DataAuthorization) -> None:
        """Tests may pass a temporary path; runners always use ``DEFAULT_LEDGER``."""
        self.auth = auth
        self._path = path
        with closing(sqlite3.connect(path, isolation_level=None)) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS requests (id INTEGER PRIMARY KEY, auth_digest TEXT,"
                " url TEXT, attempt INTEGER, at REAL, outcome TEXT)"
            )

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path, isolation_level=None)

    def reserve(self, url: str, now: datetime, *, attempt: int = 0) -> int:
        a = self.auth
        if now.tzinfo is None or not a.issued_at <= now < a.expires_at:
            raise AuthorizationRefused("authorization is not currently valid")
        if attempt > a.max_retries:
            raise AuthorizationRefused("retry budget exhausted")
        base = _check_url(url, PROVIDER_HOSTS[a.provider])
        if not a.allows_url(url):
            raise AuthorizationRefused("URL is outside the authorized scope")
        with closing(self._conn()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            used = conn.execute("SELECT COUNT(*) FROM requests WHERE auth_digest=?",
                                (a.digest,)).fetchone()[0]
            if used >= a.max_requests:
                conn.execute("ROLLBACK")
                raise AuthorizationRefused("authorized request budget exhausted")
            cur = conn.execute(
                "INSERT INTO requests (auth_digest, url, attempt, at, outcome) VALUES (?,?,?,?,?)",
                (a.digest, base, attempt, now.timestamp(), "RESERVED"),
            )
            conn.execute("COMMIT")
            return int(cur.lastrowid or 0)

    def record(self, request_id: int, outcome: str) -> None:
        with closing(self._conn()) as conn:
            updated = conn.execute(
                "UPDATE requests SET outcome=? WHERE id=? AND auth_digest=? AND outcome='RESERVED'",
                (outcome[:64], request_id, self.auth.digest),
            ).rowcount
        if updated != 1:
            raise AuthorizationRefused("unknown or already-recorded request")

    def used(self) -> int:
        with closing(self._conn()) as conn:
            return int(conn.execute("SELECT COUNT(*) FROM requests WHERE auth_digest=?",
                                    (self.auth.digest,)).fetchone()[0])


def claim_authorization(auth_path: Path, auth: DataAuthorization) -> Path:
    """Create a one-time ``.consumed`` marker next to the signed file; refuse if present.

    Together with the fixed ``DEFAULT_LEDGER`` this stops a signed authorization from
    being re-run with a fresh ledger or output directory.
    """
    marker = auth_path.with_name(auth_path.name + f".{auth.digest[:16]}.consumed")
    try:
        with marker.open("x", encoding="ascii") as stream:
            stream.write(auth.digest)
    except FileExistsError:
        raise AuthorizationRefused("authorization was already used") from None
    return marker


def prepare(auth: DataAuthorization, out_dir: Path) -> tuple[Path, Path]:
    """Write the authorization JSON and its digest; never signs anything."""
    out_dir.mkdir(parents=True, exist_ok=True)
    auth_path = out_dir / f"{auth.authorization_id}.json"
    digest_path = out_dir / f"{auth.authorization_id}.digest"
    if auth_path.exists() or digest_path.exists():
        raise AuthorizationRefused("refusing to overwrite an existing authorization")
    auth_path.write_text(auth.canonical(), encoding="utf-8")
    digest_path.write_text(auth.digest, encoding="ascii")
    return auth_path, digest_path


def signing_command(digest_path: Path, digest: str) -> str:
    """PowerShell command for the owner; it re-checks the digest before signing."""
    key = "$HOME" + chr(92) + ".ssh" + chr(92) + "sidedeck_approval"
    return (
        f"$d = (Get-Content -Raw '{digest_path}').Trim(); "
        f"if ($d -ne '{digest}') {{ throw 'digest mismatch' }}; "
        f"[IO.File]::WriteAllText('{digest_path}.payload', $d); "
        f"ssh-keygen -Y sign -f {key} -n {NAMESPACE} '{digest_path}.payload'"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare (never sign) a data authorization")
    parser.add_argument("json_file", help="draft authorization JSON")
    parser.add_argument("--out-dir", default="data/authorizations")
    args = parser.parse_args(argv)
    auth = DataAuthorization.from_json(Path(args.json_file).read_text(encoding="utf-8"))
    _, digest_path = prepare(auth, Path(args.out_dir))
    print(f"AUTHORIZATION_DIGEST={auth.digest}")
    print("OWNER_SIGNING_COMMAND=" + signing_command(digest_path, auth.digest))
    print("NETWORK_REQUESTS=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
