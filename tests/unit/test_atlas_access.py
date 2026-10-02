"""Access rules for Atlas graphs: who may list, read, edit and delete.

Predicate tests plus _load_graph and list_graphs over a scripted fake session.
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

from fastapi.responses import JSONResponse

from app.routers.atlas import (
    ATLAS_KIND,
    _load_graph,
    can_delete_graph,
    can_edit_graph,
    can_view_graph,
    graph_ownership,
    list_graphs,
)
from models.resource_share import SharePermission
from models.user import UserRole

TENANT_A = uuid.uuid4()
TENANT_B = uuid.uuid4()


def _user(role=UserRole.USER, tenant=TENANT_A):
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant,
        role=role,
        email="u@x.io",
        full_name="U",
    )


def _graph(owner, *, tenant=TENANT_A):
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant,
        owner_user_id=owner.id if owner else None,
        name="g",
        description="",
        kb_id=None,
        version=1,
        node_count=0,
        edge_count=0,
        settings={},
        created_at=None,
        updated_at=None,
    )


class _Result:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value

    def all(self):
        return self.value or []

    def scalars(self):
        return self


class _FakeDB:
    """Answers queries in order and records each statement."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.statements = []

    async def execute(self, stmt):
        self.statements.append(stmt)
        return _Result(self.answers.pop(0) if self.answers else None)


def _load(g, user, share=None, need="view"):
    db = _FakeDB(g, share, [])
    return asyncio.run(_load_graph(db, str(g.id), user, need=need))


def _status(res):
    return res.status_code if isinstance(res, JSONResponse) else 200


# ── predicates ────────────────────────────────────────────────────────


def test_owner_can_do_everything():
    owner = _user()
    g = _graph(owner)
    assert can_view_graph(g, owner)
    assert can_edit_graph(g, owner)
    assert can_delete_graph(g, owner)
    assert graph_ownership(g, owner) == "mine"


def test_member_without_share_gets_nothing():
    owner, other = _user(), _user()
    g = _graph(owner)
    assert not can_view_graph(g, other)
    assert not can_edit_graph(g, other)
    assert not can_delete_graph(g, other)


def test_view_share_reads_but_cannot_write():
    owner, viewer = _user(), _user()
    g = _graph(owner)
    assert can_view_graph(g, viewer, SharePermission.VIEW)
    assert not can_edit_graph(g, viewer, SharePermission.VIEW)
    assert not can_edit_graph(g, viewer, SharePermission.EXECUTE)
    assert graph_ownership(g, viewer) == "shared"


def test_edit_share_writes_but_cannot_delete():
    owner, editor = _user(), _user()
    g = _graph(owner)
    assert can_edit_graph(g, editor, SharePermission.EDIT)
    assert not can_delete_graph(g, editor)


def test_admin_can_do_everything_in_tenant_only():
    owner = _user()
    admin_a = _user(UserRole.ADMIN)
    admin_b = _user(UserRole.ADMIN, tenant=TENANT_B)
    g = _graph(owner)
    assert can_view_graph(g, admin_a)
    assert can_edit_graph(g, admin_a)
    assert can_delete_graph(g, admin_a)
    assert not can_view_graph(g, admin_b)
    assert not can_edit_graph(g, admin_b, SharePermission.EDIT)


def test_platform_graph_is_readable_but_admin_only_to_change():
    g = _graph(None)
    member = _user()
    assert graph_ownership(g, member) == "platform"
    assert can_view_graph(g, member)
    assert not can_edit_graph(g, member)
    assert not can_delete_graph(g, member)
    assert can_delete_graph(g, _user(UserRole.ADMIN))


# ── _load_graph status codes ──────────────────────────────────────────


def test_load_hides_other_members_graph_with_404():
    owner, other = _user(), _user()
    g = _graph(owner)
    for need in ("view", "edit", "delete"):
        assert _status(_load(g, other, need=need)) == 404


def test_load_hides_cross_tenant_graph_with_404():
    g = _graph(_user())
    assert _status(_load(g, _user(UserRole.ADMIN, tenant=TENANT_B))) == 404


def test_load_view_share_reads_and_gets_403_on_write():
    owner, viewer = _user(), _user()
    g = _graph(owner)
    ok = _load(g, viewer, SharePermission.VIEW)
    assert ok is g
    assert g._access["can_edit"] is False
    assert g._access["permission"] == "view"
    assert _status(_load(g, viewer, SharePermission.VIEW, "edit")) == 403
    assert _status(_load(g, viewer, SharePermission.VIEW, "delete")) == 403


def test_load_edit_share_writes_and_gets_403_on_delete():
    owner, editor = _user(), _user()
    g = _graph(owner)
    assert _load(g, editor, SharePermission.EDIT, "edit") is g
    assert _status(_load(g, editor, SharePermission.EDIT, "delete")) == 403


def test_load_owner_and_admin_pass_every_level():
    owner, admin = _user(), _user(UserRole.ADMIN)
    g = _graph(owner)
    for who in (owner, admin):
        for need in ("view", "edit", "delete"):
            assert _load(g, who, need=need) is g


# ── list ──────────────────────────────────────────────────────────────


def _list_sql(user, shares=()):
    db = _FakeDB(list(shares), [], [])
    asyncio.run(list_graphs(request=None, user=user, db=db, limit=50))
    share_stmt, graph_stmt = db.statements[0], db.statements[1]
    return str(share_stmt), str(graph_stmt)


def test_member_list_is_scoped_to_own_platform_and_shared():
    member = _user()
    share_sql, graph_sql = _list_sql(member)
    assert "resource_shares" in share_sql
    assert "atlas_graphs.owner_user_id =" in graph_sql
    assert "owner_user_id IS NULL" in graph_sql
    assert "atlas_graphs.id IN" not in graph_sql
    _, with_share = _list_sql(member, [(uuid.uuid4(), SharePermission.VIEW)])
    assert "atlas_graphs.id IN" in with_share


def test_admin_list_is_the_whole_tenant():
    _, graph_sql = _list_sql(_user(UserRole.ADMIN))
    assert "atlas_graphs.tenant_id =" in graph_sql
    assert "owner_user_id" not in graph_sql.split("WHERE", 1)[1]


def test_share_kind_name():
    assert ATLAS_KIND == "atlas_graph"
