"""Notification transport boundary. Strictly disabled until independent release.

No network, provider token, retry worker, or implicit switch to SENT is present.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class NotificationDeliveryNotReleased(PermissionError):
    pass


class DisabledNotificationTransport:
    """Fail-closed default implementation of the outbound notification boundary."""

    delivery_released = False

    def send(self, incident: Mapping[str, Any], *, destination: str) -> None:
        # Refuse unconditionally, before interpreting any caller supplied
        # destination/incident/provider settings. In particular, caller-provided
        # 'authorized' or 'released' flags must never grant this capability.
        raise NotificationDeliveryNotReleased(
            "outbound incident notifications are not configured or released"
        )

    def status(self) -> dict[str, Any]:
        return {
            "schema": "sidedeck.sd152.notification-transport-status/1",
            "transport": "DISABLED",
            "delivery_released": False,
            "provider_authenticated": False,
            "provider_receipt_verified": False,
            "safe_to_trade": False,
            "execution_release": "ETORO_DEMO_NOT_RELEASED",
        }
