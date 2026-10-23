from sidedeck.agents import TradingAgentsPreparation


def test_tradingagents_preparation_is_offline_and_fixture_only() -> None:
    preparation = TradingAgentsPreparation()

    assert preparation.network_enabled is False
    assert preparation.broker_tools_enabled is False
    assert preparation.model_credentials_required is True
    assert preparation.repository == "TauricResearch/TradingAgents"
