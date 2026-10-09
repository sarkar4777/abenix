"""Follow-ups to the agent access rules: duplicate and conversation reads.

Router handlers called directly with a recording session. No database.
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest

from app.routers import agents as agents_router
from app.routers import conversations as conv_router
from app.services import agent_share
from models.agent import AgentStatus, AgentType
from models.user import UserRole

TENANT_A = uuid.uuid4()
FORBIDDEN = "You do not have access to this agent"
# Query() defaults do not resolve when the handler is called directly
PAGING = dict(page=1, per_page=50, archived=False, app_slug="", agent_slug="")


def _user(role=UserRole.USER, tenant=TENANT_A):
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant, role=role, email="u@x.io")


def _agent(creator, *, tenant=TENANT_A, agent_type=AgentType.CUSTOM):
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant,
        creator_id=creator.id if creator else None,
        agent_type=agent_type,
        is_published=False,
        status=AgentStatus.ACTIVE,
        name="Pricing",
        slug="pricing",
        description="d",
        system_prompt="the secret prompt",
        model_config_={"model": "m"},
        category=None,
        icon_url=None,
    )


def _conversation(owner, agent):
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=TENANT_A,
        user_id=owner.id,
        agent_id=agent.id,
        agent_slug=agent.slug,
        app_slug=None,
        subject_type="user",
        subject_id=str(owner.id),
        title="t",
        model_used=None,
        is_archived=False,
        is_shared=False,
        share_token=None,
        total_tokens=0,
        total_cost=0,
        message_count=0,
        last_message_preview=None,
        created_at=None,
        updated_at=None,
        messages=[],
    )


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self.rows)

    def first(self):
        return self.rows[0] if self.rows else None

    def scalar(self):
        return len(self.rows)

    def scalar_one_or_none(self):
        return self.rows[0] if self.rows else None


class RecordingDB:
    """Answers each execute with the next queued row list, then empty."""

    def __init__(self, *queued):
        self.queued = list(queued)
        self.statements: list[str] = []
        self.added: list = []

    async def execute(self, stmt, params=None):
        self.statements.append(str(stmt))
        rows = self.queued.pop(0) if self.queued else []
        return FakeResult(rows)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        return None

    async def rollback(self):
        return None

    async def commit(self):
        return None

    async def refresh(self, obj):
        return None


def _request():
    return SimpleNamespace(state=SimpleNamespace())


def _body(resp) -> dict:
    return json.loads(resp.body)


@pytest.fixture
def shares(monkeypatch):
    """Control which agent ids are shared with the caller."""
    granted: set[uuid.UUID] = set()

    async def fake_ids(db, user, *, kind, minimum_permission):
        return set(granted)

    monkeypatch.setattr(agent_share, "accessible_resource_ids", fake_ids)
    return granted


# ── duplicate ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_viewer_cannot_duplicate_unshared_agent(shares):
    owner, viewer = _user(), _user()
    a = _agent(owner)
    db = RecordingDB([a])
    resp = await agents_router.duplicate_agent(a.id, user=viewer, db=db)
    assert resp.status_code == 403
    assert _body(resp)["error"]["message"] == FORBIDDEN
    assert db.added == []


@pytest.mark.asyncio
async def test_viewer_with_view_share_can_duplicate(shares):
    owner, viewer = _user(), _user()
    a = _agent(owner)
    shares.add(a.id)
    db = RecordingDB([a])
    resp = await agents_router.duplicate_agent(a.id, user=viewer, db=db)
    assert resp.status_code == 201
    clone = db.added[0]
    assert clone.creator_id == viewer.id
    assert clone.system_prompt == a.system_prompt
    assert clone.agent_type == AgentType.CUSTOM
    assert clone.slug.startswith("pricing-copy-")


@pytest.mark.asyncio
async def test_owner_and_admin_still_duplicate(shares):
    owner, admin = _user(), _user(UserRole.ADMIN)
    a = _agent(owner)
    for who in (owner, admin):
        resp = await agents_router.duplicate_agent(a.id, user=who, db=RecordingDB([a]))
        assert resp.status_code == 201


# ── conversations ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_viewer_cannot_list_other_users_conversation_on_unshared_agent(
    monkeypatch,
):
    viewer = _user()

    async def no_agents(db, user, **_):
        return set()

    monkeypatch.setattr(conv_router, "accessible_agent_ids", no_agents)
    db = RecordingDB()
    resp = await conv_router.list_conversations(
        _request(), user=viewer, db=db, **PAGING
    )
    assert resp.status_code == 200
    # the filter stays on the caller's own threads
    assert "conversations.agent_id IN" not in db.statements[0]
    assert "conversations.subject_id" in db.statements[0]


@pytest.mark.asyncio
async def test_list_widens_to_threads_on_shared_agents(monkeypatch):
    owner, viewer = _user(), _user()
    a = _agent(owner)

    async def shared(db, user, **_):
        return {a.id}

    monkeypatch.setattr(conv_router, "accessible_agent_ids", shared)
    db = RecordingDB()
    await conv_router.list_conversations(_request(), user=viewer, db=db, **PAGING)
    assert "conversations.agent_id IN" in db.statements[0]


@pytest.mark.asyncio
async def test_delegated_subject_never_widens_by_agent(monkeypatch):
    viewer = _user()
    called = []

    async def spy(db, user, **_):
        called.append(True)
        return {uuid.uuid4()}

    monkeypatch.setattr(conv_router, "accessible_agent_ids", spy)
    request = SimpleNamespace(
        state=SimpleNamespace(
            acting_subject=SimpleNamespace(subject_type="app_user", subject_id="7")
        )
    )
    db = RecordingDB()
    await conv_router.list_conversations(request, user=viewer, db=db, **PAGING)
    assert called == []
    assert "conversations.agent_id IN" not in db.statements[0]


@pytest.mark.asyncio
async def test_viewer_cannot_read_other_users_thread_on_unshared_agent(shares):
    owner, viewer = _user(), _user()
    a = _agent(owner)
    conv = _conversation(owner, a)
    db = RecordingDB([conv], [a])
    resp = await conv_router.get_conversation(
        str(conv.id), _request(), user=viewer, db=db
    )
    assert resp.status_code == 403
    assert _body(resp)["error"]["message"] == "Forbidden"


@pytest.mark.asyncio
async def test_view_share_on_agent_opens_its_threads(shares):
    owner, viewer = _user(), _user()
    a = _agent(owner)
    shares.add(a.id)
    conv = _conversation(owner, a)
    db = RecordingDB([conv], [a])
    resp = await conv_router.get_conversation(
        str(conv.id), _request(), user=viewer, db=db
    )
    assert resp.status_code == 200
    assert _body(resp)["data"]["id"] == str(conv.id)


@pytest.mark.asyncio
async def test_platform_agent_does_not_open_other_users_threads(shares):
    owner, viewer = _user(UserRole.ADMIN), _user()
    oob = _agent(owner, agent_type=AgentType.OOB)
    conv = _conversation(owner, oob)
    db = RecordingDB([conv], [oob])
    resp = await conv_router.get_conversation(
        str(conv.id), _request(), user=viewer, db=db
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_conversation_on_unshared_agent_is_forbidden(shares):
    owner, viewer = _user(), _user()
    a = _agent(owner)
    db = RecordingDB([a])
    resp = await conv_router.create_conversation(
        {"agent_id": str(a.id)}, _request(), user=viewer, db=db
    )
    assert resp.status_code == 403
    assert _body(resp)["error"]["message"] == FORBIDDEN
    assert db.added == []
