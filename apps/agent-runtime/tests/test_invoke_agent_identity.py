"""invoke_agent runs the sub-agent as the caller, links it to the parent and caps nesting."""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwt

from engine.tools import invoke_agent as ia
from engine.tools.invoke_agent import InvokeAgentTool, mint_user_token

TENANT = str(uuid.uuid4())
OTHER_TENANT = str(uuid.uuid4())
USER = str(uuid.uuid4())
PARENT_EXEC = str(uuid.uuid4())
_REAL_CLIENT = httpx.AsyncClient
CALLER_AGENT = str(uuid.uuid4())
CHILD_AGENT = str(uuid.uuid4())
CHILD_EXEC = str(uuid.uuid4())

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PRIVATE_PEM = _KEY.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
).decode()
PUBLIC_PEM = (
    _KEY.public_key()
    .public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    .decode()
)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for k in (
        "ABENIX_PLATFORM_API_KEY",
        "INTERNAL_API_TOKEN",
        "ABENIX_INTERNAL_API_KEY",
        "PLATFORM_API_KEY",
        "SECRET_KEY",
    ):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("JWT_ALGORITHM", "RS256")
    monkeypatch.setenv("JWT_PRIVATE_KEY", PRIVATE_PEM)
    monkeypatch.setattr(ia.progress, "root_for", AsyncMock(return_value=""))
    monkeypatch.setattr(ia.asyncio, "sleep", AsyncMock(return_value=None))


def _install(monkeypatch, *, agents, execute_status=200):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.path
        if path == "/api/agents":
            return httpx.Response(200, json={"success": True, "data": agents})
        if path.endswith("/execute"):
            if execute_status != 200:
                return httpx.Response(execute_status, json={"error": "no"})
            return httpx.Response(
                200, json={"success": True, "data": {"execution_id": CHILD_EXEC}}
            )
        if path == f"/api/executions/{CHILD_EXEC}":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "status": "completed",
                        "output_message": '{"ok": true}',
                        "parent_execution_id": PARENT_EXEC,
                    }
                },
            )
        return httpx.Response(404)

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return _REAL_CLIENT(*args, **kwargs)

    monkeypatch.setattr(ia.httpx, "AsyncClient", factory)
    return seen


def _agent(agent_id=CHILD_AGENT, tenant=TENANT, slug="child-agent"):
    return {"id": agent_id, "slug": slug, "name": "Child", "tenant_id": tenant}


def _tool(**kw):
    base = dict(
        tenant_id=TENANT,
        execution_id=PARENT_EXEC,
        agent_id=CALLER_AGENT,
        user_id=USER,
        user_role="creator",
        api_base="http://api.test",
    )
    base.update(kw)
    return InvokeAgentTool(**base)


def test_minted_token_carries_access_claims_and_verifies():
    token = mint_user_token(USER, TENANT, "creator")
    claims = jwt.decode(token, PUBLIC_PEM, algorithms=["RS256"])
    assert set(claims) == {"sub", "tenant_id", "role", "type", "exp", "iat"}
    assert claims["sub"] == USER
    assert claims["tenant_id"] == TENANT
    assert claims["role"] == "creator"
    assert claims["type"] == "access"
    assert claims["exp"] - claims["iat"] == 300


def test_hs_algorithm_signs_with_secret_key(monkeypatch):
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")
    monkeypatch.setenv("SECRET_KEY", "s3cret-for-tests")
    token = mint_user_token(USER, TENANT, "user")
    claims = jwt.decode(token, "s3cret-for-tests", algorithms=["HS256"])
    assert claims["sub"] == USER and claims["type"] == "access"


@pytest.mark.asyncio
async def test_runs_as_caller_and_links_parent(monkeypatch):
    monkeypatch.setenv("ABENIX_PLATFORM_API_KEY", "af_platform")
    seen = _install(monkeypatch, agents=[_agent()])
    res = await _tool(delegation_depth=1).execute(
        {"agent_slug": "child-agent", "input": {"q": 1}}
    )
    assert not res.is_error, res.content
    for req in seen:
        assert "x-api-key" not in req.headers
        token = req.headers["authorization"].split(" ", 1)[1]
        claims = jwt.decode(token, PUBLIC_PEM, algorithms=["RS256"])
        assert claims["sub"] == USER and claims["tenant_id"] == TENANT
    post = next(r for r in seen if r.method == "POST")
    body = json.loads(post.content)
    assert body["parent_execution_id"] == PARENT_EXEC
    assert body["delegation_depth"] == 2
    env = json.loads(res.content)
    assert env["execution_id"] == CHILD_EXEC
    assert env["parent_execution_id"] == PARENT_EXEC
    assert res.metadata["execution_id"] == CHILD_EXEC


@pytest.mark.asyncio
async def test_platform_key_only_without_user_and_same_tenant_only(monkeypatch):
    monkeypatch.setenv("ABENIX_PLATFORM_API_KEY", "af_platform")
    seen = _install(monkeypatch, agents=[_agent(tenant=OTHER_TENANT)])
    res = await _tool(user_id="").execute({"agent_slug": "child-agent", "input": {}})
    assert res.is_error
    assert res.content == "agent slug not found or not shared with you: child-agent"
    assert seen[0].headers["x-api-key"] == "af_platform"
    assert not any(r.method == "POST" for r in seen)

    seen = _install(monkeypatch, agents=[_agent()])
    res = await _tool(user_id="").execute({"agent_slug": "child-agent", "input": {}})
    assert not res.is_error, res.content
    assert all(r.headers.get("x-api-key") == "af_platform" for r in seen)


@pytest.mark.asyncio
async def test_no_user_and_no_key_refuses(monkeypatch):
    seen = _install(monkeypatch, agents=[_agent()])
    res = await _tool(user_id="").execute({"agent_slug": "child-agent", "input": {}})
    assert res.is_error and "platform API key" in res.content
    assert seen == []


@pytest.mark.asyncio
async def test_unsigned_caller_never_falls_back_to_platform_key(monkeypatch):
    monkeypatch.setenv("ABENIX_PLATFORM_API_KEY", "af_platform")
    monkeypatch.delenv("JWT_PRIVATE_KEY")
    monkeypatch.setattr(ia, "mint_user_token", lambda *a, **k: "")
    seen = _install(monkeypatch, agents=[_agent()])
    res = await _tool().execute({"agent_slug": "child-agent", "input": {}})
    assert res.is_error and "Could not sign" in res.content
    assert seen == []


@pytest.mark.asyncio
async def test_depth_over_three_refused(monkeypatch):
    seen = _install(monkeypatch, agents=[_agent()])
    res = await _tool(delegation_depth=3).execute(
        {"agent_slug": "child-agent", "input": {}}
    )
    assert res.is_error
    assert res.content == "sub-agent depth limit reached (3)"
    assert seen == []


@pytest.mark.asyncio
async def test_depth_three_child_still_allowed(monkeypatch):
    seen = _install(monkeypatch, agents=[_agent()])
    res = await _tool(delegation_depth=2).execute(
        {"agent_slug": "child-agent", "input": {}}
    )
    assert not res.is_error, res.content
    post = next(r for r in seen if r.method == "POST")
    assert json.loads(post.content)["delegation_depth"] == 3


@pytest.mark.asyncio
async def test_self_invoke_refused(monkeypatch):
    seen = _install(monkeypatch, agents=[_agent(agent_id=CALLER_AGENT)])
    res = await _tool().execute({"agent_slug": "child-agent", "input": {}})
    assert res.is_error and "cannot invoke itself" in res.content
    assert not any(r.method == "POST" for r in seen)


@pytest.mark.asyncio
async def test_forbidden_execute_reads_as_not_shared(monkeypatch):
    _install(monkeypatch, agents=[_agent()], execute_status=403)
    res = await _tool().execute({"agent_slug": "child-agent", "input": {}})
    assert res.is_error
    assert res.content == "agent slug not found or not shared with you: child-agent"


def test_registry_hands_caller_identity_to_the_tool():
    from engine.agent_executor import build_tool_registry

    reg = build_tool_registry(
        ["invoke_agent"],
        agent_id=CALLER_AGENT,
        tenant_id=TENANT,
        execution_id=PARENT_EXEC,
        user_id=USER,
        user_role="admin",
        delegation_depth=2,
    )
    tool = reg.get("invoke_agent")
    assert tool is not None
    assert tool._user_id == USER
    assert tool._user_role == "admin"
    assert tool._execution_id == PARENT_EXEC
    assert tool._agent_id == CALLER_AGENT
    assert tool._depth == 2
