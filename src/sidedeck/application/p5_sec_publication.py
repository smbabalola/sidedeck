"""Offline SEC publication timing and first eligible valuation session."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sidedeck.application.us_equity_calendar import is_regular_session

EASTERN = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class SecPublication:
    accession: str
    form: str
    accepted_at: datetime
    official_url: str


def first_eligible_close(publication: SecPublication) -> date:
    """Return the first regular-session close strictly after publication.

    A filing accepted at or after 16:00 ET cannot affect that day's closing
    valuation. The strict next-session rule also avoids same-day look-ahead.
    """
    accepted = publication.accepted_at
    if accepted.tzinfo is None:
        raise ValueError("SEC accepted timestamp must be timezone-aware")
    eastern = accepted.astimezone(EASTERN)
    candidate = eastern.date() + timedelta(days=1)
    while not is_regular_session(candidate):
        candidate += timedelta(days=1)
    return candidate
