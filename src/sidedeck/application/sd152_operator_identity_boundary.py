"""Operator authentication boundary: no local actor claim is an authenticated principal.

An external identity verifier may be added only with independent review.
This default implementation cannot issue an operator session or broker grant.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


class OperatorAuthenticationDenied(PermissionError):
    pass


@dataclass(frozen=True)
class VerifiedOperator:
    subject: str
    issuer: str
    tenant: str
    roles: frozenset[str]
    expires_at: datetime


class OperatorIdentityVerifier(Protocol):
    def verify(self, token: str, *, audience: str, at: datetime) -> VerifiedOperator: ...


class DisabledOperatorIdentityVerifier:
    """Mandatory default: even plausible/forged tokens fail before validation."""

    identity_provider_configured = False

    def verify(self, token: str, *, audience: str, at: datetime) -> VerifiedOperator:
        raise OperatorAuthenticationDenied(
            "operator identity issuer and validation are not configured"
        )
