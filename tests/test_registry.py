from mcp.server.mcpserver import MCPServer
from mcp_solar.tools import register_all


def _names(profile):
    return set(register_all(MCPServer("t"), profile=profile))


def test_granular_profile_hides_the_composite_tool():
    n = _names("granular")
    assert "assess_property" not in n
    assert {"geocode_address", "estimate_solar_production", "estimate_savings"} <= n


def test_composite_profile_hides_the_granular_chain():
    n = _names("composite")
    assert "assess_property" in n
    assert "geocode_address" not in n
    assert "estimate_solar_production" not in n


def test_all_profile_exposes_everything():
    n = _names("all")
    assert {"assess_property", "geocode_address", "estimate_solar_production",
            "estimate_savings", "save_assessment", "list_assessments"} <= n


def test_autodiscovery_found_every_tool_module():
    # S6: adding a tool must be one file. If this drops, the walk broke.
    assert len(_names("all")) >= 6
