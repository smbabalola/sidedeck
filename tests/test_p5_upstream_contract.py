from sidedeck.application.p5_upstream_contract import probe


def test_contract_probe_is_read_only_and_always_no_go():
    result = probe()
    assert result["agent_research_run"] == "NOT_ATTEMPTED"
    assert result["broker_execution"] == "DISABLED"
    assert result["buffett_ready"] is False
    assert result["installed_upstream_legacy_bridge_contract"] in {"PRESENT", "MISSING"}
    assert "hedge_fund.signals.buffett" in result["modules"]
    assert "hedge_fund.data.models" in result["modules"]
