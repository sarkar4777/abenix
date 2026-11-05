"""Regression tests for the runtime fixes to the cache, gates, moderation and tools."""

from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from engine import credentials, moderation_client, url_guard
from engine.agent_executor import AgentExecutor
from engine.cache.exact_cache import ExactCache, _cache_key
from engine.llm_router import LLMResponse, LLMRouter, StreamEvent
from engine.moderation_gate import GateConfig
from engine.pipeline_validator import _has_unresolvable_template
from engine.tools.base import BaseTool, ToolRegistry, ToolResult
from engine.tools.code_executor import CodeExecutorTool, _validate_code
from engine.tools.database_writer import DatabaseWriterTool
from engine.tools.http_client import HttpClientTool

ROOT = Path(__file__).resolve().parents[2]
MSG = [{"role": "user", "content": "hi"}]


def test_exact_key_separates_tenant_agent_and_prompt():
    base = _cache_key("m", MSG, None, 0.3, "t1", "prompt", "a1")
    assert base == _cache_key("m", MSG, None, 0.3, "t1", "prompt", "a1")
    assert base != _cache_key("m", MSG, None, 0.3, "t2", "prompt", "a1")
    assert base != _cache_key("m", MSG, None, 0.3, "t1", "other", "a1")
    assert base != _cache_key("m", MSG, None, 0.3, "t1", "prompt", "a2")


class _Redis:
    def __init__(self):
        self.store = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.store[key] = value


@pytest.mark.asyncio
async def test_one_tenants_answer_is_not_served_to_another():
    cache = ExactCache.__new__(ExactCache)
    cache._redis = _Redis()
    answer = {"content": "secret"}
    await cache.set("m", MSG, None, 0.3, answer, "t1", "p", "a")
    assert await cache.get("m", MSG, None, 0.3, "t1", "p", "a") == answer
    assert await cache.get("m", MSG, None, 0.3, "t2", "p", "a") is None
    assert await cache.get("m", MSG, None, 0.3, "t1", "other", "a") is None


def _executor(content="ok", gate=None, big=False, tools=False, on_stop="final"):
    async def complete(**kwargs):
        if "used all the steps" in str(kwargs["messages"][-1].get("content")):
            return LLMResponse(
                content=on_stop,
                model="claude-sonnet-4-5",
                input_tokens=1,
                output_tokens=1,
                cost=0.0,
                latency_ms=1,
            )
        tc = {"id": "t1", "name": "echo", "arguments": {}} if tools else None
        if kwargs.get("stream"):

            async def gen():
                if tc:
                    yield StreamEvent(event="tool_call", data=tc)
                else:
                    yield StreamEvent(event="token", data=content)
                yield StreamEvent(
                    event="done",
                    data={
                        "model": "claude-sonnet-4-5",
                        "input_tokens": 1,
                        "output_tokens": 1,
                        "cost": 0.0,
                        "tool_calls": [tc] if tc else [],
                    },
                )

            return gen()
        return LLMResponse(
            content="" if tc else content,
            model="claude-sonnet-4-5",
            input_tokens=1,
            output_tokens=1,
            cost=0.0,
            latency_ms=1,
            tool_calls=[tc] if tc else [],
        )

    class Echo(BaseTool):
        name = "echo"
        description = "echo"
        input_schema = {"type": "object", "properties": {}}

        async def execute(self, arguments):
            return ToolResult(content="x", metadata={})

    router = LLMRouter()
    provider = MagicMock()
    provider.complete = complete
    router._providers["anthropic"] = provider
    reg = ToolRegistry()
    reg.register(Echo())
    return AgentExecutor(
        llm_router=router,
        tool_registry=reg,
        model="claude-sonnet-4-5",
        max_tokens=16000 if big else 4096,
        max_iterations=1,
        moderation_gate=gate,
    )


@pytest.mark.asyncio
async def test_invoke_with_claude_and_a_large_max_tokens_returns_the_text():
    result = await _executor("the answer", big=True).invoke("q")
    assert result.output == "the answer"


def _dlp_gate():
    return GateConfig(tenant_id="t", moderation=False, dlp_mode="block")


@pytest.mark.asyncio
async def test_step_limit_answer_is_checked_on_invoke():
    ex = _executor(gate=_dlp_gate(), tools=True, on_stop="mail me at a@b.example")
    result = await ex.invoke("q")
    assert result.moderation_blocked is True
    assert "a@b.example" not in result.output


@pytest.mark.asyncio
async def test_step_limit_answer_is_checked_on_stream():
    ex = _executor(gate=_dlp_gate(), tools=True, on_stop="mail me at a@b.example")
    events = [e async for e in ex.stream("q")]
    tokens = "".join(str(e.data) for e in events if e.event == "token")
    assert "a@b.example" not in tokens
    done = [e for e in events if e.event == "done"][-1]
    assert done.data["moderation_blocked"] is True


@pytest.mark.asyncio
async def test_step_limit_answer_is_masked_when_policy_masks():
    gate = GateConfig(tenant_id="t", moderation=False, dlp_mode="mask")
    ex = _executor(gate=gate, tools=True, on_stop="mail me at a@b.example")
    result = await ex.invoke("q")
    assert "a@b.example" not in result.output


@pytest.mark.asyncio
async def test_moderation_uses_the_saved_key(monkeypatch):
    seen = {}

    class Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"results": []}

    class Client:
        def __init__(self, **_k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        async def post(self, _url, headers=None, json=None):
            seen.update(headers)
            return Resp()

    monkeypatch.setattr(moderation_client.httpx, "AsyncClient", Client)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with credentials.override({"OPENAI_API_KEY": "saved-in-admin"}):
        await moderation_client._call_openai("hello", "omni-moderation-latest")
    assert seen["Authorization"] == "Bearer saved-in-admin"


@pytest.mark.asyncio
async def test_moderation_fails_closed_when_the_policy_says_so(monkeypatch):
    from engine.moderation_gate import ModerationBlocked, check

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with credentials.override({"OPENAI_API_KEY": ""}):
        with pytest.raises(ModerationBlocked):
            await check(
                "hello",
                source="pre_llm",
                config=GateConfig(pre_llm=True, fail_closed=True),
            )


async def _run_required_if(value):
    from engine.pipeline import PipelineExecutor, parse_pipeline_nodes

    calls = []

    class Marker(BaseTool):
        name = "marker"
        description = "m"
        input_schema = {"type": "object", "properties": {}}

        async def execute(self, arguments):
            calls.append(arguments)
            return ToolResult(content="ran", metadata={})

    reg = ToolRegistry()
    reg.register(Marker())
    nodes = parse_pipeline_nodes(
        [{"id": "n", "tool_name": "marker", "arguments": {}, "required_if": value}]
    )
    await PipelineExecutor(tool_registry=reg, timeout_seconds=5).execute(nodes, {})
    return calls


@pytest.mark.parametrize(
    "value",
    [
        "{{len(x.items) > 0}}",
        "{{a.b < 3 or c.d}}",
        "{{missing.field}}",
        "prefix {{missing.field}}",
    ],
)
@pytest.mark.asyncio
async def test_required_if_that_cannot_resolve_skips_the_step(value):
    assert await _run_required_if(value) == []


@pytest.mark.asyncio
async def test_required_if_with_a_real_value_still_runs():
    assert len(await _run_required_if("yes")) == 1


def test_validator_rejects_an_expression_in_required_if():
    from engine.pipeline_validator import validate_pipeline

    reg = ToolRegistry()
    bad = validate_pipeline(
        [
            {
                "id": "n",
                "tool_name": "x",
                "arguments": {},
                "required_if": "{{len(a.b) > 0}}",
            }
        ],
        reg,
    )
    assert any(e.field == "required_if" for e in bad.errors)
    good = validate_pipeline(
        [{"id": "n", "tool_name": "x", "arguments": {}, "required_if": "{{input.b}}"}],
        reg,
    )
    assert not any(e.field == "required_if" for e in good.errors)
    assert _has_unresolvable_template("{{a.b}}") is False


def test_no_shipped_pipeline_has_a_required_if_that_cannot_resolve():
    bad = []
    for path in (ROOT / "packages/db/seeds/agents").glob("*.yaml"):
        for match in re.finditer(r"required_if:\s*\"([^\"]*)\"", path.read_text()):
            if _has_unresolvable_template(match.group(1)):
                bad.append((path.name, match.group(1)))
    assert bad == []


@pytest.mark.parametrize(
    "code",
    [
        "import zipfile\nzipfile.os.system('id')",
        "import tarfile\ntarfile.os.environ",
        "import random\nrandom._os.environ",
        "from zipfile import os\nos.system('id')",
        "import random\nrandom.__dict__['_os']",
        "(x for x in []).gi_frame.f_globals",
        "'{0.os.environ}'.format(__import__('zipfile'))",
        "s = '{0.os}'\ns.format(1)",
        "import pandas\npandas.read_pickle('x')",
    ],
)
def test_code_executor_validator_catches_known_escapes(code):
    assert _validate_code(code) != []


@pytest.mark.parametrize(
    "code",
    [
        "import re\nre.compile('a').match('a')",
        "'{:.2f} {}'.format(1.5, 'x')",
        "class A:\n    def __init__(self):\n        self._x = 1\n    def x(self):\n        return self._x\nA().x()",
        "import collections\ncollections.namedtuple('P', 'x')(1)._asdict()",
        "type(1).__name__",
    ],
)
def test_code_executor_validator_keeps_ordinary_code(code):
    assert _validate_code(code) == []


@pytest.mark.parametrize(
    "code",
    [
        "getattr(__import__('zipfile'), 'o' + 's')",
        "getattr(type(1), '__sub' + 'classes__')()",
        "import pandas\npandas.read_csv('/etc/passwd')",
        "import gzip\ngzip.open('/etc/passwd').read()",
    ],
)
@pytest.mark.asyncio
async def test_code_executor_blocks_escapes_at_run_time(code):
    res = await CodeExecutorTool().execute({"code": code})
    assert res.is_error
    assert "root:" not in res.content


@pytest.mark.asyncio
async def test_code_executor_still_writes_exports():
    res = await CodeExecutorTool().execute(
        {"code": "path = save_export('hardening.txt', 'ok')\nresult = len(path) > 0"}
    )
    assert not res.is_error and "true" in res.content.lower()


@pytest.mark.parametrize(
    "arguments",
    [
        {"operation": "insert", "table": "af_x; DROP TABLE users", "rows": [{"a": 1}]},
        {"operation": "insert", "table": "af_x", "rows": [{"a) VALUES (1); --": 1}]},
        {
            "operation": "upsert",
            "table": "af_x",
            "rows": [{"a": 1}],
            "conflict_column": "a) DO NOTHING; DROP TABLE users; --",
        },
        {
            "operation": "create_table",
            "table": "af_x",
            "columns": {"a": "TEXT); DROP TABLE users; --"},
        },
        {
            "operation": "create_table",
            "table": "af_x",
            "columns": {"a; DROP TABLE users": "TEXT"},
        },
    ],
)
@pytest.mark.asyncio
async def test_database_writer_refuses_injection(monkeypatch, arguments):
    connected = []

    class Conn:
        async def execute(self, sql, *_a):
            connected.append(sql)

        async def close(self):
            return None

    async def connect(*_a, **_k):
        return Conn()

    import asyncpg

    monkeypatch.setattr(asyncpg, "connect", connect)
    res = await DatabaseWriterTool("postgresql://u@h/d").execute(arguments)
    assert res.is_error
    assert connected == []


@pytest.mark.asyncio
async def test_database_writer_keeps_plain_columns(monkeypatch):
    connected = []

    class Conn:
        async def execute(self, sql, *_a):
            connected.append(sql)

        async def close(self):
            return None

    async def connect(*_a, **_k):
        return Conn()

    import asyncpg

    monkeypatch.setattr(asyncpg, "connect", connect)
    res = await DatabaseWriterTool("postgresql://u@h/d").execute(
        {
            "operation": "create_table",
            "table": "af_ok",
            "columns": {"name": "VARCHAR(20) NOT NULL", "n": "NUMERIC(10, 2)"},
        }
    )
    assert not res.is_error
    assert json.loads(res.content)["table"] == "af_ok"


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",
        "http://localhost:8000/api/health",
        "http://127.0.0.1/",
        "http://abenix-postgresql.default.svc.cluster.local/",
    ],
)
@pytest.mark.asyncio
async def test_http_client_refuses_internal_targets(monkeypatch, url):
    monkeypatch.delenv("CONNECTORS_ALLOW_PRIVATE_TARGETS", raising=False)
    res = await HttpClientTool().execute({"url": url})
    assert res.is_error and res.metadata["blocked"] is True


@pytest.mark.asyncio
async def test_http_client_checks_every_redirect_hop(monkeypatch):
    import aiohttp

    monkeypatch.delenv("CONNECTORS_ALLOW_PRIVATE_TARGETS", raising=False)

    async def public(_host, _port):
        return ["93.184.216.34"]

    monkeypatch.setattr(url_guard, "_resolve", public)
    asked = []

    class Resp:
        status = 302
        headers = {"Location": "http://169.254.169.254/latest/"}
        content_type = "text/plain"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

    class Session:
        def __init__(self, *_a, **_k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        def request(self, method, **kwargs):
            asked.append(kwargs["url"])
            return Resp()

    monkeypatch.setattr(aiohttp, "ClientSession", Session)
    res = await HttpClientTool().execute({"url": "http://public.example/"})
    assert res.is_error and res.metadata["blocked"] is True
    assert asked == ["http://public.example/"]


@pytest.mark.asyncio
async def test_agent_step_uses_the_registry_tenant_not_the_arguments(monkeypatch):
    from types import SimpleNamespace

    from engine.tools import agent_step

    seen = {}

    async def breach(_agent, tenant, _url):
        seen["tenant"] = tenant
        return SimpleNamespace(message="stop", details=lambda: {})

    monkeypatch.setattr(agent_step, "_budget_breach", breach)
    tool = agent_step.AgentStepTool(tenant_id="real-tenant")
    res = await tool.execute(
        {"input_message": "x", "system_prompt": "y", "__tenant_id__": "victim"}
    )
    assert res.is_error
    assert seen["tenant"] == "real-tenant"


def test_pipeline_slug_lookup_is_tenant_scoped():
    source = (ROOT / "apps/agent-runtime/engine/pipeline.py").read_text()
    i = source.index("async def _resolve_agent_by_slug")
    block = source[i : i + 1800]
    assert "upper(agent_type::text) = 'OOB'" in block
    assert "CAST(tenant_id AS text) = :tid" in block


def test_shipped_seed_required_ifs_parse():
    data = yaml.safe_load(
        (ROOT / "packages/db/seeds/agents/98_sla_sweep_pipeline.yaml").read_text()
    )
    guards = {
        n["id"]: n.get("required_if")
        for n in data["pipeline_config"]["nodes"]
        if n.get("required_if")
    }
    assert guards["approval_gate"] == "{{rescore_sla.breaching}}"
    assert guards["slack_escalate"] == "{{approval_gate.approved}}"
