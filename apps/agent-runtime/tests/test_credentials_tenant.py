"""The tenant layer of the resolver and the context that selects it.

A tenant row beats the platform row, which beats the environment. The tenant
comes from a contextvar the executor sets, with the tool's own tenant_id as
the fallback, and it must not leak between tasks.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from engine import credentials
from engine.tools.base import BaseTool, ConfigField, ToolResult

T1 = "11111111-1111-1111-1111-111111111111"
T2 = "22222222-2222-2222-2222-222222222222"


@pytest.fixture(autouse=True)
def _clean_resolver(monkeypatch):
    credentials.configure(loader=None, ttl=30)
    credentials._snapshot.clear()
    credentials._tenant_snapshot.clear()
    monkeypatch.setattr(credentials, "_file_defaults", {})
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("PROBE_KEY", raising=False)
    token = credentials.set_tenant("")
    yield
    credentials.reset_tenant(token)
    credentials.configure(loader=None, ttl=30)
    credentials._snapshot.clear()
    credentials._tenant_snapshot.clear()


# --- precedence --------------------------------------------------------------


def test_tenant_beats_platform_beats_env(monkeypatch):
    monkeypatch.setenv("PROBE_KEY", "from-env")
    credentials._snapshot["PROBE_KEY"] = "from-platform"
    credentials._tenant_snapshot[(T1, "PROBE_KEY")] = "from-tenant"

    assert credentials.get("PROBE_KEY", tenant_id=T1) == "from-tenant"
    assert credentials.source("PROBE_KEY", tenant_id=T1) == "tenant"
    # another tenant falls through to the platform row
    assert credentials.get("PROBE_KEY", tenant_id=T2) == "from-platform"
    assert credentials.source("PROBE_KEY", tenant_id=T2) == "stored"
    # "" ignores tenant rows altogether, that is the platform view
    assert credentials.source("PROBE_KEY", tenant_id="") == "stored"

    credentials._snapshot.clear()
    assert credentials.get("PROBE_KEY", tenant_id=T2) == "from-env"
    assert credentials.source("PROBE_KEY", tenant_id=T2) == "env"
    assert credentials.get("PROBE_KEY", tenant_id=T1) == "from-tenant"


def test_override_still_beats_the_tenant_row():
    credentials._tenant_snapshot[(T1, "PROBE_KEY")] = "from-tenant"
    with credentials.override({"PROBE_KEY": "pinned"}):
        assert credentials.get("PROBE_KEY", tenant_id=T1) == "pinned"
        assert credentials.source("PROBE_KEY", tenant_id=T1) == "override"


def test_tenant_value_and_tenant_keys_read_one_tenant_only():
    credentials._tenant_snapshot[(T1, "PROBE_KEY")] = "a"
    credentials._tenant_snapshot[(T2, "PROBE_KEY")] = "b"
    credentials._tenant_snapshot[(T1, "OTHER")] = "c"
    assert credentials.tenant_value("PROBE_KEY", T1) == "a"
    assert credentials.tenant_value("PROBE_KEY", "") == ""
    assert credentials.tenant_keys(T1) == {"PROBE_KEY": "a", "OTHER": "c"}
    assert credentials.tenant_keys(T2) == {"PROBE_KEY": "b"}


# --- the context -------------------------------------------------------------


def test_context_selects_the_tenant_when_none_is_passed():
    credentials._snapshot["PROBE_KEY"] = "from-platform"
    credentials._tenant_snapshot[(T1, "PROBE_KEY")] = "from-tenant"
    assert credentials.current_tenant() == ""
    assert credentials.get("PROBE_KEY") == "from-platform"
    token = credentials.set_tenant(T1)
    try:
        assert credentials.current_tenant() == T1
        assert credentials.get("PROBE_KEY") == "from-tenant"
        assert credentials.source("PROBE_KEY") == "tenant"
    finally:
        credentials.reset_tenant(token)
    assert credentials.get("PROBE_KEY") == "from-platform"


def test_set_tenant_normalises_uuid_and_none():
    import uuid

    u = uuid.UUID(T1)
    credentials.set_tenant(u)
    assert credentials.current_tenant() == T1
    credentials.set_tenant(None)
    assert credentials.current_tenant() == ""


@pytest.mark.asyncio
async def test_context_does_not_leak_between_tasks():
    credentials._tenant_snapshot[(T1, "PROBE_KEY")] = "one"
    credentials._tenant_snapshot[(T2, "PROBE_KEY")] = "two"

    async def run_as(tenant: str) -> str:
        credentials.set_tenant(tenant)
        await asyncio.sleep(0)
        return credentials.get("PROBE_KEY")

    got = await asyncio.gather(run_as(T1), run_as(T2), run_as(""))
    assert got == ["one", "two", ""]
    assert credentials.current_tenant() == ""


# --- refresh -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_tenant_loader_fills_the_tenant_snapshot():
    async def platform():
        return {"PROBE_KEY": "from-platform"}

    async def tenants():
        return {(T1, "PROBE_KEY"): "from-tenant"}

    credentials.configure(loader=platform, tenant_loader=tenants, ttl=60)
    await credentials.ensure_fresh()
    assert credentials.get("PROBE_KEY", tenant_id=T1) == "from-tenant"
    assert credentials.get("PROBE_KEY", tenant_id=T2) == "from-platform"


@pytest.mark.asyncio
async def test_failed_tenant_read_keeps_the_previous_tenant_snapshot():
    async def tenants():
        return {(T1, "PROBE_KEY"): "v1"}

    credentials.configure(tenant_loader=tenants, ttl=60)
    await credentials.ensure_fresh()
    assert credentials.get("PROBE_KEY", tenant_id=T1) == "v1"

    async def broken():
        raise RuntimeError("db down")

    credentials.configure(tenant_loader=broken, ttl=60)
    await credentials.ensure_fresh(force=True)
    assert credentials.get("PROBE_KEY", tenant_id=T1) == "v1"


@pytest.mark.asyncio
async def test_missing_tenant_table_is_not_an_error():
    class _Conn:
        async def fetch(self, sql: str, *args: Any):
            raise RuntimeError('relation "tenant_tool_credentials" does not exist')

    assert await credentials._read_tenant_table(_Conn()) == {}


# --- BaseTool ----------------------------------------------------------------


class _Probe(BaseTool):
    name = "probe_tenant_tool"
    description = "probe"
    input_schema: dict[str, Any] = {"type": "object", "properties": {}}
    config_fields = (ConfigField("PROBE_KEY", kind="secret", required=True),)

    def __init__(self, tenant_id: str = "") -> None:
        self.tenant_id = tenant_id

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(content=self.cfg("PROBE_KEY", required=True))


@pytest.mark.asyncio
async def test_cfg_falls_back_to_the_tools_own_tenant():
    credentials._snapshot["PROBE_KEY"] = "from-platform"
    credentials._tenant_snapshot[(T1, "PROBE_KEY")] = "from-tenant"
    assert (await _Probe(tenant_id=T1).execute({})).content == "from-tenant"
    assert (await _Probe().execute({})).content == "from-platform"
    # the wrapper resets what it set
    assert credentials.current_tenant() == ""


@pytest.mark.asyncio
async def test_context_wins_over_the_tools_own_tenant():
    credentials._tenant_snapshot[(T1, "PROBE_KEY")] = "one"
    credentials._tenant_snapshot[(T2, "PROBE_KEY")] = "two"
    credentials.set_tenant(T2)
    assert (await _Probe(tenant_id=T1).execute({})).content == "two"


@pytest.mark.asyncio
async def test_missing_for_this_tenant_is_the_standard_result():
    credentials._tenant_snapshot[(T1, "PROBE_KEY")] = "one"
    r = await _Probe(tenant_id=T2).execute({})
    assert r.is_error
    assert "PROBE_KEY is not configured" in r.content
