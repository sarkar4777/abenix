"""drafts=mine keeps the caller's own drafts and hides everyone else's."""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects import postgresql


def _sql(clause) -> str:
    return str(
        clause.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


def test_own_drafts_predicate():
    from app.routers.agents import _own_drafts_only

    uid = uuid.uuid4()
    sql = _sql(_own_drafts_only(SimpleNamespace(id=uid)))
    assert "agents.status != 'DRAFT'" in sql
    assert f"agents.creator_id = '{uid}'" in sql
    assert " OR " in sql


def _list(monkeypatch, **kw):
    import app.core.permissions as perms
    import app.routers.agents as ag

    monkeypatch.setattr(perms, "accessible_resource_ids", AsyncMock(return_value=set()))
    seen = {}

    async def execute(query):
        seen["sql"] = _sql(query)
        res = MagicMock()
        res.scalars.return_value.all.return_value = []
        return res

    db = MagicMock()
    db.scalar = AsyncMock(return_value=0)
    db.execute = execute
    user = SimpleNamespace(
        id=uuid.uuid4(), tenant_id=uuid.uuid4(), role=SimpleNamespace(value="user")
    )
    args = dict(
        search="",
        slug="",
        category="",
        status="",
        mode="",
        sort="name",
        scope="all",
        published=None,
        drafts="all",
        limit=100,
        offset=0,
    )
    args.update(kw)
    asyncio.run(ag.list_agents(**args, user=user, db=db))
    return seen["sql"], user


def test_list_with_drafts_mine_filters_other_peoples_drafts(monkeypatch):
    sql, user = _list(monkeypatch, drafts="mine")
    assert "agents.status != 'DRAFT'" in sql
    assert f"agents.creator_id = '{user.id}'" in sql


def test_list_defaults_to_every_visible_draft(monkeypatch):
    sql, _ = _list(monkeypatch)
    assert "agents.status != 'DRAFT'" not in sql


@pytest.mark.parametrize("bad", ["none", "others", ""])
def test_drafts_param_is_validated(bad):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import app.routers.agents as ag
    from app.core.deps import get_current_user, get_db

    app = FastAPI()
    app.include_router(ag.router)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=uuid.uuid4(), tenant_id=uuid.uuid4(), role=SimpleNamespace(value="user")
    )
    app.dependency_overrides[get_db] = lambda: MagicMock()
    r = TestClient(app).get(f"/api/agents?drafts={bad}")
    assert r.status_code == 422
