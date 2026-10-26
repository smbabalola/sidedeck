from sidedeck.application.sd113_day_trader_api import day_trader_summary


def test_day_trader_summary_is_research_only_and_has_all_capabilities() -> None:
    data = day_trader_summary()
    assert data["module"] == "DAY_TRADER"
    assert data["book"] == "DAY_TRADER_SKILL"
    assert data["mode"] == "RESEARCH_ONLY"
    assert data["execution_enabled"] is False
    assert data["broker_execution"] == "DISABLED"
    assert data["data_status"] == "NO_APPROVED_INTRADAY_DATA"
    assert data["source"]["license"] == "MIT"
    assert len(data["capabilities"]) == 11
    assert data["opportunities"] == []
    assert data["plans"] == []


def test_day_trader_summary_never_exposes_credentials_or_order_controls() -> None:
    data = repr(day_trader_summary()).lower()
    for forbidden in ("alpaca_api", "etoro", "api_secret", "private_key", "submit_order"):
        assert forbidden not in data
