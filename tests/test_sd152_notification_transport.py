"""No caller-provided report can activate the default notification transport."""
import pytest

from sidedeck.application.sd152_notification_transport import (
    DisabledNotificationTransport, NotificationDeliveryNotReleased,
)


@pytest.mark.parametrize("incident", [
    {},
    {"authorized": True, "provider_configured": True},
    {"delivery_released": True, "status": "SENT"},
    {"execution_release": "RELEASED", "safe_to_trade": True},
])
def test_disabled_transport_refuses_all_attempts(incident):
    transport = DisabledNotificationTransport()
    with pytest.raises(NotificationDeliveryNotReleased):
        transport.send(incident, destination="operator@example.invalid")
    state = transport.status()
    assert state["transport"] == "DISABLED"
    assert state["delivery_released"] is False
    assert state["provider_receipt_verified"] is False
    assert state["execution_release"] == "ETORO_DEMO_NOT_RELEASED"
