"""Agent memories are tenant-scoped and only owners, editors or admins delete them."""

from __future__ import annotations

import asyncio
import inspect
import uuid
from types import SimpleNamespace

from app.routers import memories
from models.resource_share import SharePermission
from models.user import UserRole

T = uuid.uuid4()


class _Res:
    def __init__(self, v):
        self.v = v

    def scalar_one_or_none(self):
        return self.v


class _DB:
    def __init__(self, agent):
        self.agent = agent

    async def execute(self, stmt):
        return _Res(self.agent)


def _user(role=UserRole.USER):
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=T, role=role)


def _check(monkeypatch, agent, user, manage, can_view=True, can_edit=False):
    import app.services.agent_share as share

    async def resolve(db, u, a, permission_required=SharePermission.VIEW):
        return can_edit if permission_required == SharePermission.EDIT else can_view

    monkeypatch.setattr(share, "resolve_agent_access", resolve)
    return asyncio.run(
        memories._memory_agent(_DB(agent), agent.id, user, manage=manage)
    )


def test_viewer_reads_but_cannot_delete(monkeypatch):
    agent = SimpleNamespace(id=uuid.uuid4(), tenant_id=T, creator_id=uuid.uuid4())
    u = _user()
    assert _check(monkeypatch, agent, u, False) is None
    assert _check(monkeypatch, agent, u, True).status_code == 403


def test_owner_editor_and_admin_delete(monkeypatch):
    owner = _user()
    agent = SimpleNamespace(id=uuid.uuid4(), tenant_id=T, creator_id=owner.id)
    assert _check(monkeypatch, agent, owner, True) is None
    assert _check(monkeypatch, agent, _user(UserRole.ADMIN), True) is None
    assert _check(monkeypatch, agent, _user(), True, can_edit=True) is None


def test_platform_agent_memories_need_an_admin_to_delete(monkeypatch):
    agent = SimpleNamespace(id=uuid.uuid4(), tenant_id=None, creator_id=None)
    assert _check(monkeypatch, agent, _user(), True, can_edit=True).status_code == 403


def test_no_access_is_404(monkeypatch):
    agent = SimpleNamespace(id=uuid.uuid4(), tenant_id=T, creator_id=uuid.uuid4())
    assert _check(monkeypatch, agent, _user(), False, can_view=False).status_code == 404


def test_queries_are_tenant_scoped():
    for fn in (
        memories.list_memories,
        memories.delete_memory,
        memories.bulk_delete_memories,
    ):
        assert "AgentMemory.tenant_id == user.tenant_id" in inspect.getsource(fn)
