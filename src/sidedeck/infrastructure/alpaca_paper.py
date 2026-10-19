"""SideDeck-only Alpaca paper account binding, with network execution prohibited."""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

PAPER_HOST = "paper-api.alpaca.markets"


@dataclass(frozen=True)
class AlpacaPaperBinding:
    account_name: str = "SideDeckdemo"
    api_key_env: str = "ALPACA_API_KEY2"
    api_secret_env: str = "ALPACA_API_SECRET_KEY2"
    base_url: str = "https://paper-api.alpaca.markets"
    enabled: bool = False

    def __post_init__(self) -> None:
        parsed = urlparse(self.base_url)
        if (parsed.scheme != "https" or parsed.hostname != PAPER_HOST
                or parsed.port is not None or parsed.username is not None
                or parsed.password is not None or parsed.path not in ("", "/")
                or parsed.query or parsed.fragment):
            raise ValueError("only the exact Alpaca paper-trading host is permitted")
        if self.api_key_env != "ALPACA_API_KEY2":
            raise ValueError("SideDeck must not use SignalDeck's ALPACA_API_KEY")
        if self.api_secret_env != "ALPACA_API_SECRET_KEY2":
            raise ValueError("SideDeck must use its own separate secret reference")
        if self.enabled:
            raise ValueError("broker network access is not enabled in P2")


def submit_order(*_args: object, **_kwargs: object) -> None:
    raise PermissionError("Alpaca order submission is disabled in SideDeck P2")
