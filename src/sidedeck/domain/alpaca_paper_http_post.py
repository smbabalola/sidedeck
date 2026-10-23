"""Locked-down Alpaca PAPER POST transport: disabled in product code.

This is a separately reviewed boundary that can only target the paper host.
No SideDeck CLI imports/enables this class; production writes remain disabled
until a separate owner-approved local acceptance/release. CI substitutes a
fake opener; no network/credentials are used in tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from http.client import HTTPMessage
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .paper_desk import PaperDeskError, PaperOrderDraft
from .paper_post_contract import build_paper_post_preview

NETWORK_PAPER_WRITES_ENABLED = False
MAX_RESPONSE_BYTES = 100_000


@dataclass(frozen=True)
class RestrictedPaperAuth:
    """Paper credentials stay in memory only, never repr/log/GitHub."""

    api_key: str = field(repr=False)
    secret_key: str = field(repr=False)


@dataclass(frozen=True)
class PaperOrderPermit:
    """Order-scoped permission metadata; release gate still disabled."""

    client_order_id: str
    key_slot: str
    expires_at: datetime
    verified_account_slot: bool = False
    owner_confirmed: bool = False


class _DenyRedirect(HTTPRedirectHandler):
    def redirect_request(
        self, req: Request, fp: Any, code: int, msg: str,
        headers: HTTPMessage, newurl: str,
    ) -> None:
        raise PaperDeskError("paper order redirect forbidden")


class AlpacaPaperPostTransport:
    """One bounded paper POST, only after all explicit permission gates pass.

    NEVER imported by the default SideDeck runner and never activated here.
    """

    def __init__(self, auth: RestrictedPaperAuth) -> None:
        self._auth = auth

    def send(
        self, draft: PaperOrderDraft, *, permit: PaperOrderPermit, now: datetime,
    ) -> tuple[int, dict[str, Any]]:
        if not NETWORK_PAPER_WRITES_ENABLED:
            raise PaperDeskError("Alpaca PAPER writes disabled; no owner-approved release")
        if now.tzinfo is None or now.utcoffset() is None:
            raise PaperDeskError("paper write time must have timezone")
        if permit.expires_at.tzinfo is None or permit.expires_at.utcoffset() is None:
            raise PaperDeskError("paper write permit has no timezone")
        if not (permit.owner_confirmed and permit.verified_account_slot):
            raise PaperDeskError("paper write account / owner authorisation missing")
        if (permit.client_order_id != draft.client_order_id
            or permit.key_slot != draft.key_slot):
            raise PaperDeskError("write permit belongs to different order or paper account")
        if now.astimezone(timezone.utc) > permit.expires_at.astimezone(timezone.utc):
            raise PaperDeskError("paper order write permit expired")
        if not self._auth.api_key or not self._auth.secret_key:
            raise PaperDeskError("missing paper credential pair")
        preview = build_paper_post_preview(draft)
        data = json.dumps(preview.body, separators=(",", ":"), sort_keys=True).encode()
        req = Request(
            preview.url,
            method="POST",
            data=data,
            headers={
                "APCA-API-KEY-ID": self._auth.api_key,
                "APCA-API-SECRET-KEY": self._auth.secret_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with build_opener(_DenyRedirect()).open(req, timeout=10) as response:
                payload = response.read(MAX_RESPONSE_BYTES + 1)
                status = response.status
        except HTTPError as exc:
            # An HTTP failure may happen after external acceptance. Do NOT
            # retry. Return status only, never raw provider content.
            code = exc.code
            exc.close()
            return code, {}
        except URLError:
            raise PaperDeskError("paper order outcome uncertain; do not retry") from None
        if len(payload) > MAX_RESPONSE_BYTES:
            raise PaperDeskError("paper order response too large; do not retry")
        if status not in (200, 201):
            return status, {}
        try:
            decoded = json.loads(payload.decode())
        except (ValueError, UnicodeDecodeError) as exc:
            raise PaperDeskError("paper order response invalid; do not retry") from exc
        if not isinstance(decoded, dict):
            raise PaperDeskError("paper order response must be object")
        return status, decoded
