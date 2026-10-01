"""Sandbox guarantees for LLM-generated tools and the pipeline's unknown-tool path."""

from __future__ import annotations

import logging

from engine.pipeline import PipelineExecutor, PipelineNode
from engine.tools import dynamic_tool as dt
from engine.tools.base import BaseTool, ToolRegistry, ToolResult
from engine.tools.dynamic_tool import DynamicTool, validate_code


def _tool(code: str, **kw) -> DynamicTool:
    return DynamicTool("t", "test tool", code, [], **kw)


class TestValidator:
    def test_dunder_subscript_escape_rejected(self):
        code = 'result = vars(json)["__builtins__"]["__import__"]("os").environ'
        errors = validate_code(code)
        assert any("vars" in e for e in errors)
        assert any("__builtins__" in e for e in errors)

    def test_dunder_key_on_plain_dict_rejected(self):
        assert validate_code('x = {}\ny = x["__class__"]')

    def test_dunder_attribute_rejected(self):
        assert validate_code("result = ().__class__.__bases__")

    def test_module_attribute_hop_rejected(self):
        assert validate_code("import uuid\nresult = uuid.os.environ")
        assert validate_code("result = datetime.sys.modules")

    def test_subscript_on_module_rejected(self):
        assert validate_code('import json\nresult = json["x"]')

    def test_introspection_builtins_rejected(self):
        for name in (
            "getattr",
            "type",
            "globals",
            "locals",
            "__import__",
            "eval",
            "exec",
            "compile",
            "open",
            "dir",
            "vars",
        ):
            assert validate_code(f"result = {name}"), name

    def test_format_field_walk_rejected(self):
        assert validate_code('result = "{0.__globals__}".format(len)')
        assert validate_code('result = "{0[x]}".format(arguments)')
        assert validate_code('tpl = "{}"\nresult = tpl.format(1)')

    def test_pandas_numpy_rejected(self):
        assert validate_code("import pandas as pd")
        assert validate_code("import numpy")
        assert validate_code("from io import StringIO")

    def test_wildcard_import_rejected(self):
        assert validate_code("from math import *")

    def test_plain_code_accepted(self):
        code = (
            "import math\n"
            "from collections import Counter\n"
            "class Acc:\n"
            "    def __init__(self):\n"
            "        self.n = 0\n"
            "c = Counter(arguments.get('items', []))\n"
            "result = {'n': len(c), 'pi': round(math.pi, 2), 'msg': '{} ok'.format('all')}\n"
        )
        assert validate_code(code) == []


class TestRuntime:
    async def test_escape_chain_is_error(self):
        res = await _tool(
            'result = vars(json)["__builtins__"]["__import__"]("os").environ'
        ).execute({})
        assert res.is_error
        assert "validation failed" in res.content

    async def test_vars_absent_even_without_validator(self, monkeypatch):
        monkeypatch.setattr(dt, "validate_code", lambda code: [])
        res = await _tool('result = vars(json)["__builtins__"]').execute({})
        assert res.is_error
        assert "NameError" in res.content

    async def test_module_hop_blocked_at_runtime(self, monkeypatch):
        monkeypatch.setattr(dt, "validate_code", lambda code: [])
        res = await _tool("import uuid\nresult = uuid.os.environ").execute({})
        assert res.is_error
        assert "AttributeError" in res.content

    async def test_forbidden_import_blocked_at_runtime(self, monkeypatch):
        monkeypatch.setattr(dt, "validate_code", lambda code: [])
        res = await _tool("import os\nresult = os.getcwd()").execute({})
        assert res.is_error
        assert "ImportError" in res.content

    async def test_timeout_returns_is_error(self, monkeypatch):
        monkeypatch.setattr(dt, "MAX_EXECUTION_TIME", 0.3)
        args = {"run": True}
        res = await _tool("while arguments['run']:\n    pass\nresult = 1").execute(args)
        args["run"] = False
        assert res.is_error
        assert "timed out" in res.content

    async def test_result_capped(self):
        res = await _tool("result = 'x' * 120000").execute({})
        assert not res.is_error
        assert len(res.content) < 50_200
        assert "truncated, 120000 chars total" in res.content

    async def test_stdout_capped_and_captured(self):
        res = await _tool("print('y' * 70000)").execute({})
        assert "truncated" in res.content
        assert res.content.startswith("y")

    async def test_dict_result_and_arguments(self):
        code = "import statistics\nresult = {'mean': statistics.mean(arguments['xs']), 'd': datetime.date(2020, 1, 2).isoformat()}"
        res = await _tool(code).execute({"xs": [1, 2, 3]})
        assert not res.is_error
        assert '"mean": 2' in res.content
        assert "2020-01-02" in res.content

    async def test_stored_input_schema_wins(self):
        schema = {
            "type": "object",
            "properties": {"q": {"type": "string"}},
            "required": ["q"],
        }
        t = _tool("result = 1", input_schema=schema)
        assert t.input_schema == schema


class _Echo(BaseTool):
    name = "echo"
    description = "echo"
    input_schema = {"type": "object", "properties": {}}

    async def execute(self, arguments):
        return ToolResult(content="ok")


class TestPipelineUnknownTool:
    async def test_unknown_tool_fails_without_generation(self, monkeypatch):
        called = []

        async def _gen(*a, **k):
            called.append(a)
            return _Echo()

        monkeypatch.setattr(dt, "generate_dynamic_tool", _gen)
        reg = ToolRegistry()
        reg.register(_Echo())
        result = await PipelineExecutor(reg).execute(
            [PipelineNode(id="n1", tool_name="ghost")]
        )
        nr = result.node_results["n1"]
        assert nr.status == "failed"
        assert nr.error == "Unknown tool 'ghost'"
        assert nr.error_type == "tool_error"
        assert called == []
        assert reg.get("ghost") is None


class TestRegistryLoader:
    def test_fetch_skips_without_tenant_or_db(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        assert dt.fetch_saved_tools("", "", ["a"]) == {}
        assert dt.fetch_saved_tools("t1", "", ["a"]) == {}

    def test_only_approved_saved_tools_load(self, monkeypatch, caplog):
        from engine import agent_executor as ae

        rows = {
            "good": {
                "name": "good",
                "description": "d",
                "code": "result = 1",
                "input_schema": {},
                "permissions": {},
                "status": "approved",
            },
            "waiting": {
                "name": "waiting",
                "description": "d",
                "code": "result = 1",
                "input_schema": {},
                "permissions": {},
                "status": "pending",
            },
        }
        seen = {}

        def _fake(tenant_id, db_url, names, timeout=5.0):
            seen["names"] = list(names)
            return rows

        monkeypatch.setattr(dt, "fetch_saved_tools", _fake)
        with caplog.at_level(logging.WARNING, logger="engine.agent_executor"):
            reg = ae.build_tool_registry(
                ["calculator", "good", "waiting", "nope"],
                agent_id="agent-1",
                tenant_id="tenant-1",
                db_url="postgresql://x",
            )
        assert set(seen["names"]) == {"good", "waiting", "nope"}
        assert isinstance(reg.get("good"), DynamicTool)
        assert reg.get("waiting") is None
        assert reg.get("nope") is None
        text = caplog.text
        assert "waiting" in text and "not approved" in text and "agent-1" in text
        assert "Unknown tool requested: nope" in text
