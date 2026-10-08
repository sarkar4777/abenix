from __future__ import annotations

from app.routers.pipeline_healing import with_node_tools


def test_new_step_tool_joins_the_agent_tools():
    cfg = {"tools": ["calculator"], "mode": "pipeline"}
    nodes = {
        "nodes": [
            {"id": "a", "tool_name": "calculator"},
            {"id": "b", "tool_name": "json_transformer"},
            {"id": "c", "type": "agent", "tool_name": "agent_step"},
        ]
    }
    out = with_node_tools(cfg, nodes)
    assert out["tools"] == ["calculator", "json_transformer"]
    assert out["mode"] == "pipeline"
    assert cfg["tools"] == ["calculator"]


def test_no_nodes_leaves_tools_alone():
    assert with_node_tools({"tools": ["x"]}, None)["tools"] == ["x"]
