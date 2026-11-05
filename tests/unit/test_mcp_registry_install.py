"""Registry install takes every id form, and the catalogue fills itself on a fresh install."""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from app.routers import mcp
from app.schemas.mcp import RegistryInstallRequest

ENTRY_ID = uuid.uuid4()
ENTRY = SimpleNamespace(
    id=ENTRY_ID,
    registry_id="github-mcp",
    name="GitHub",
    server_url="https://api.githubcopilot.com/mcp",
    auth_type="oauth2",
)


class _Result:
    def __init__(self, value):
        self.value = value

    def first(self):
        return self.value

    def scalar_one_or_none(self):
        return self.value

    def scalars(self):
        return SimpleNamespace(all=lambda: self.value or [])


class FakeDB:
    def __init__(self, *results):
        self.results = list(results)
        self.added = []
        self.statements = []
        self.commits = 0

    async def execute(self, stmt):
        self.statements.append(str(stmt))
        return _Result(self.results.pop(0) if self.results else None)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        pass

    async def refresh(self, obj):
        pass


@pytest.mark.parametrize(
    "body",
    [
        {"registry_id": "github-mcp", "server_name": "GitHub"},
        {"registry_id": "github-mcp"},
        {"registry_entry_id": "github-mcp"},
        {"registry_entry_id": str(ENTRY_ID)},
        {"id": str(ENTRY_ID)},
    ],
)
def test_every_id_form_validates(body):
    assert RegistryInstallRequest(**body).entry_ref in ("github-mcp", str(ENTRY_ID))


def test_no_id_is_a_validation_error():
    with pytest.raises(ValidationError):
        RegistryInstallRequest(server_name="GitHub")


async def _install(body):
    # the row check, then the entry lookup
    db = FakeDB((ENTRY_ID,), ENTRY)
    user = SimpleNamespace(id=uuid.uuid4(), tenant_id=uuid.uuid4())
    with (
        patch.object(mcp, "log_action", AsyncMock()),
        patch.object(mcp, "_serialize_connection", lambda c: {"name": c.server_name}),
    ):
        resp = await mcp.install_from_registry(
            RegistryInstallRequest(**body), user=user, db=db
        )
    return resp, db


@pytest.mark.asyncio
async def test_install_by_entry_uuid_defaults_the_name():
    resp, db = await _install({"registry_entry_id": str(ENTRY_ID)})
    assert resp.status_code == 201
    assert json.loads(resp.body)["data"]["name"] == "GitHub"
    assert db.added[0].server_url == ENTRY.server_url


@pytest.mark.asyncio
async def test_install_keeps_a_name_the_client_chose():
    resp, _db = await _install({"registry_id": "github-mcp", "server_name": "Work"})
    assert json.loads(resp.body)["data"]["name"] == "Work"


@pytest.mark.asyncio
async def test_browse_seeds_an_empty_catalogue_once():
    user = SimpleNamespace(id=uuid.uuid4(), tenant_id=uuid.uuid4())
    db = FakeDB()
    await mcp.browse_registry(db=db, _user=user)
    assert {e.registry_id for e in db.added} == {
        e["registry_id"] for e in mcp._CURATED_REGISTRY
    }
    assert db.commits == 1


@pytest.mark.asyncio
async def test_browse_leaves_a_filled_catalogue_alone():
    user = SimpleNamespace(id=uuid.uuid4(), tenant_id=uuid.uuid4())
    db = FakeDB((ENTRY_ID,), [])
    await mcp.browse_registry(db=db, _user=user)
    assert db.added == [] and db.commits == 0


@pytest.mark.asyncio
async def test_two_requests_seeding_together_do_not_fail():
    from sqlalchemy.exc import IntegrityError

    db = FakeDB()
    db.commit = AsyncMock(side_effect=IntegrityError("insert", {}, Exception("dup")))
    db.rollback = AsyncMock()
    await mcp._seed_registry_when_empty(db)
    db.rollback.assert_awaited_once()
