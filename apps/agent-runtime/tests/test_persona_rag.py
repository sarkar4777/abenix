"""persona_rag reads only the executing user's items and never raises."""

from __future__ import annotations

import json

import pytest

import persona_vectors as pv
from engine.tools import _meeting_session as sessmod
from engine.tools.persona_rag import PersonaRagTool

TENANT = "11111111-1111-1111-1111-111111111111"
ALICE = "22222222-2222-2222-2222-222222222222"
BOB = "33333333-3333-3333-3333-333333333333"


@pytest.fixture
def seen(monkeypatch):
    calls: list[dict] = []

    async def fake_search(engine, **kw):
        calls.append(kw)
        return [
            {
                "text": "hello",
                "score": 0.9,
                "source": "note",
                "title": "t",
                "doc_id": "d",
            }
        ], []

    monkeypatch.setattr(pv, "search", fake_search)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setattr(sessmod, "get", lambda _eid: None)
    return calls


@pytest.mark.asyncio
async def test_non_self_scope_is_searched_for_the_owner_only(seen):
    tool = PersonaRagTool(tenant_id=TENANT, user_id=ALICE, execution_id="e1")
    r = await tool.execute({"query": "walk-away price", "scope": "persona:bob"})
    assert not r.is_error
    assert seen[0]["user_id"] == ALICE
    assert seen[0]["tenant_id"] == TENANT
    assert seen[0]["scope"] == "persona:bob"


@pytest.mark.asyncio
async def test_no_executing_user_is_refused(seen):
    tool = PersonaRagTool(tenant_id=TENANT, user_id="", execution_id="e1")
    r = await tool.execute({"query": "anything"})
    assert r.is_error and not seen
    assert "executing user" in json.loads(r.content)["error"]


@pytest.mark.asyncio
async def test_meeting_session_limits_scopes_without_meeting_id(seen, monkeypatch):
    sess = sessmod.MeetingSession.__new__(sessmod.MeetingSession)
    sess.user_id = ALICE
    sess.persona_scopes = ["client:acme"]
    monkeypatch.setattr(sessmod, "get", lambda _eid: sess)
    tool = PersonaRagTool(tenant_id=TENANT, user_id=ALICE, execution_id="e1")
    denied = await tool.execute({"query": "price", "scope": "client:other"})
    assert denied.is_error and json.loads(denied.content)["scope_denied"]
    ok = await tool.execute({"query": "price", "scope": "client:acme"})
    assert not ok.is_error and seen[-1]["user_id"] == ALICE


@pytest.mark.asyncio
async def test_meeting_of_another_user_is_refused(seen, monkeypatch):
    sess = sessmod.MeetingSession.__new__(sessmod.MeetingSession)
    sess.user_id = BOB
    sess.persona_scopes = ["self"]
    monkeypatch.setattr(sessmod, "get", lambda _eid: sess)
    tool = PersonaRagTool(tenant_id=TENANT, user_id=ALICE, execution_id="e1")
    r = await tool.execute({"query": "price"})
    assert r.is_error and not seen


@pytest.mark.asyncio
async def test_store_failure_is_a_tool_error_not_a_crash(monkeypatch):
    async def broken(engine, **kw):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(pv, "search", broken)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setattr(sessmod, "get", lambda _eid: None)
    tool = PersonaRagTool(tenant_id=TENANT, user_id=ALICE, execution_id="e1")
    r = await tool.execute({"query": "anything"})
    assert r.is_error
    assert "unavailable" in json.loads(r.content)["error"]


def test_badge_reflects_embeddings_not_pinecone():
    keys = {f.key for f in PersonaRagTool.config_fields}
    assert keys == {"OPENAI_API_KEY"}
