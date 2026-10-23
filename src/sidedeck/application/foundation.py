from __future__ import annotations

from datetime import datetime

from sidedeck.domain.accounting import Ledger, opening_event
from sidedeck.domain.contracts import ExperimentManifest


def initialise_two_portfolios(manifest: ExperimentManifest, opened_at: datetime) -> Ledger:
    ledger = Ledger()
    for portfolio_id in manifest.portfolio_ids:
        ledger.append(opening_event(portfolio_id, opened_at, manifest.starting_capital_usd))
    return ledger
