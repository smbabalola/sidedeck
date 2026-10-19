from sidedeck.application.p5_upstream_contract import probe


def test_contract_probe_is_read_only_and_always_no_go():
    result = probe()
    assert result["agent_research_run"] == "NOT_ATTEMPTED"
    assert result["broker_execution"] == "DISABLED"
    assert result["buffett_ready"] is False
    assert result["installed_upstream_legacy_bridge_contract"] in {"PRESENT", "MISSING"}
    assert "hedge_fund.signals.buffett" in result["modules"]
    assert "hedge_fund.data.models" in result["modules"]


def test_probe_describes_model_requirements_without_executing_agent():
    result = probe()
    model = result['modules']['hedge_fund.data.models']
    if model['available'] and model['symbols'].get('FinancialMetrics'):
        assert isinstance(model['required_fields'], list)
    buffett = result['modules']['hedge_fund.signals.buffett']
    if buffett['available'] and buffett['symbols'].get('BuffettAgent'):
        assert isinstance(buffett['snapshot_method_available'], bool)
        assert 'predict_signature' in buffett
