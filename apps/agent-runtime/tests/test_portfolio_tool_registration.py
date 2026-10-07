"""A portfolio_<domain> tool loads for any agent, scoped to the actAs subject or the user running it."""

from engine.agent_executor import build_tool_registry


def _tool(reg, name):
    t = reg.get(name)
    assert t is not None, f"{name} was not registered"
    return t


def test_agent_built_in_the_ui_gets_the_portfolio_tool_scoped_to_its_user():
    reg = build_tool_registry(
        ["portfolio_energy_book"], tenant_id="t1", user_id="user-1", db_url=""
    )
    tool = _tool(reg, "portfolio_energy_book")
    assert tool.user_id == "user-1"


def test_actas_runs_scope_to_the_subject():
    reg = build_tool_registry(
        ["portfolio_energy_book"],
        tenant_id="t1",
        user_id="service-account",
        db_url="",
        acting_subject={"subject_id": "end-user-7", "subject_type": "user"},
    )
    assert _tool(reg, "portfolio_energy_book").user_id == "end-user-7"


def test_no_user_no_portfolio_tool():
    reg = build_tool_registry(["portfolio_energy_book"], tenant_id="t1", db_url="")
    assert reg.get("portfolio_energy_book") is None
