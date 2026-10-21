"""Licensing-aware assessment of independently displayed closing-price data."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IndependentPriceCandidate:
    source_id: str
    source_url: str
    access_status: str
    license_status: str
    coverage_status: str
    close_definition: str
    adjustment_basis: str
    independent_transport: bool


def assess_candidate(candidate: IndependentPriceCandidate) -> str:
    if not candidate.independent_transport:
        return "REJECTED_NOT_INDEPENDENT"
    if candidate.access_status != "PUBLIC" or candidate.license_status != "PERSONAL_NONCOMMERCIAL_ALLOWED":
        return "BLOCKED_LICENSE"
    if candidate.coverage_status != "COMPLETE" or candidate.close_definition != "CLOSE":
        return "BLOCKED_PROVENANCE"
    if candidate.adjustment_basis != "SPLIT_ADJUSTED_NOT_DIVIDEND_ADJUSTED":
        return "BLOCKED_ADJUSTMENT"
    return "CANDIDATE_ONLY"
