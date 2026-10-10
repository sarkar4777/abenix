"""ML model detail, edit, delete and deploy check ownership and live shares."""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

from app.routers import ml_models
from models.resource_share import SharePermission
from models.user import UserRole

T = uuid.uuid4()


def _user(role=UserRole.USER):
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=T, role=role)


def _model(owner):
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=T, created_by=owner.id)


def _run(monkeypatch, model, user, need, view=(), edit=()):
    import app.core.permissions as perms

    async def ids(db, u, *, kind, minimum_permission=SharePermission.VIEW):
        return set(edit) if minimum_permission == SharePermission.EDIT else set(view)

    monkeypatch.setattr(perms, "accessible_resource_ids", ids)
    return asyncio.run(ml_models._model_access_error(None, model, user, need))


def test_owner_and_admin_pass(monkeypatch):
    owner = _user()
    m = _model(owner)
    assert _run(monkeypatch, m, owner, "delete") is None
    assert _run(monkeypatch, m, _user(UserRole.ADMIN), "delete") is None


def test_stranger_gets_404(monkeypatch):
    m = _model(_user())
    assert _run(monkeypatch, m, _user(), "view").status_code == 404


def test_view_share_reads_but_cannot_edit(monkeypatch):
    m = _model(_user())
    viewer = _user()
    assert _run(monkeypatch, m, viewer, "view", view={m.id}) is None
    assert _run(monkeypatch, m, viewer, "edit", view={m.id}).status_code == 403


def test_edit_share_edits_but_cannot_delete(monkeypatch):
    m = _model(_user())
    editor = _user()
    assert _run(monkeypatch, m, editor, "edit", view={m.id}, edit={m.id}) is None
    resp = _run(monkeypatch, m, editor, "delete", view={m.id}, edit={m.id})
    assert resp.status_code == 403
