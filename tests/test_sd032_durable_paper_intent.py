from decimal import Decimal

import pytest

from sidedeck.application.sd032_durable_paper_intent import (
    DurablePaperIntentStore, IntentError, PaperIntent,
)


def intent(client: str = "client-1") -> PaperIntent:
    return PaperIntent("intent-1", client, "sidedeck", "alpaca", "paper", "paper-scope",
                       "tradingagents", "US:SPY", "BUY", Decimal("2"), Decimal("500"))


def test_durable_idempotency_and_restart_recovery(tmp_path):
    path = str(tmp_path / "outbox.sqlite3")
    store = DurablePaperIntentStore(path)
    assert store.enqueue(intent())["state"] == "QUEUED"
    assert store.enqueue(intent())["state"] == "QUEUED"
    store.claim("intent-1")
    store.record_simulated_submission("intent-1")
    store.acknowledge("intent-1")
    store.record_fill("intent-1", Decimal("1"))
    assert store.record_fill("intent-1", Decimal("1"))["state"] == "FILLED_SIMULATED"
    store.close()
    recovered = DurablePaperIntentStore(path)
    assert recovered.recover()[0]["state"] == "FILLED_SIMULATED"
    assert len(recovered.events("intent-1")) == 6
    recovered.close()


def test_conflicting_client_id_and_fail_closed_transitions(tmp_path):
    store = DurablePaperIntentStore(str(tmp_path / "outbox.sqlite3"))
    store.enqueue(intent())
    with pytest.raises(IntentError, match="conflicting"):
        store.enqueue(PaperIntent("other", "client-1", "sidedeck", "alpaca", "paper", "paper-scope",
                                  "tradingagents", "US:SPY", "BUY", Decimal("3"), Decimal("500")))
    with pytest.raises(IntentError, match="invalid transition"):
        store.acknowledge("intent-1")
    store.close()
