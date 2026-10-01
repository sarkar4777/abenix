"""Tenant and platform scope on the tool configuration API.

The service computes every state for a tenant, the admin router writes the
table the scope names, and /api/tools badges follow the caller's tenant.
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT / "apps" / "agent-runtime", ROOT / "apps" / "api", ROOT / "packages" / "db"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from engine import credentials  # noqa: E402
from app.routers import admin_tool_config as router  # noqa: E402
from app.services import tool_config  # noqa: E402
from models.user import UserRole  # noqa: E402

T1 = str(uuid.uuid4())
T2 = str(uuid.uuid4())
KEY = "OPENAI_API_KEY"


class RecordingDB:
    def __init__(self):
        self.statements: list[tuple[str, dict]] = []
        self.commits = 0

    async def execute(self, stmt, params=None):
        self.statements.append((" ".join(str(stmt).split()), dict(params or {})))

    async def commit(self):
        self.commits += 1


def _admin(tenant_id: str):
    return SimpleNamespace(
        id=uuid.uuid4(), tenant_id=uuid.UUID(tenant_id), role=UserRole.ADMIN, email="a@x.io"
    )


def _body(resp) -> dict:
    return json.loads(resp.body)


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    credentials.configure(loader=None, ttl=30)
    credentials._snapshot.clear()
    credentials._tenant_snapshot.clear()
    monkeypatch.delenv(KEY, raising=False)
    monkeypatch.setattr(credentials, "_file_defaults", {})

    async def _no_refresh(force: bool = False):
        return None

    monkeypatch.setattr(tool_config, "refresh", _no_refresh)
    yield
    credentials.configure(loader=None, ttl=30)
    credentials._snapshot.clear()
    credentials._tenant_snapshot.clear()


# --- service -----------------------------------------------------------------


def test_key_state_reports_both_scopes():
    d = tool_config.declarations()[KEY]
    credentials._snapshot[KEY] = "sk-platform-0000"
    credentials._tenant_snapshot[(T1, KEY)] = "sk-tenant-1111"

    st = tool_config.key_state(d, include_value=True, tenant_id=T1)
    assert st["scope"] == "tenant"
    assert st["source"] == "tenant"
    assert st["effective_source"] == "tenant"
    assert st["tenant_source"] == "tenant"
    assert st["platform_source"] == "stored"
    assert st["value"].endswith("1111")
    assert st["tenant_value"].endswith("1111")
    assert st["platform_value"].endswith("0000")

    other = tool_config.key_state(d, include_value=True, tenant_id=T2)
    assert other["source"] == "stored"
    assert other["tenant_source"] == "unset"
    assert other["value"].endswith("0000")

    plat = tool_config.key_state(d, include_value=True, tenant_id=T1, scope="platform")
    assert plat["scope"] == "platform"
    assert plat["source"] == "stored"
    assert plat["value"].endswith("0000")
    assert plat["tenant_source"] == "tenant"


def test_tool_status_follows_the_callers_tenant():
    slug = sorted(tool_config.declarations()[KEY].tools)[0]
    keys = tool_config.keys_for_tool(slug)
    for k in keys:
        credentials._tenant_snapshot[(T1, k)] = "x"
    with_tenant = tool_config.tool_status(slug, tenant_id=T1)
    without = tool_config.tool_status(slug, tenant_id=T2)
    assert with_tenant == "configured"
    assert without in ("missing", "optional")
    cfg = tool_config.tool_config_for(slug, tenant_id=T1)
    assert cfg["status"] == "configured"
    assert all(f["source"] == "tenant" for f in cfg["fields"])


@pytest.mark.asyncio
async def test_catalogue_counts_missing_for_the_scope():
    decls = tool_config.declarations()
    required = [d.key for d in decls.values() if d.required]
    assert required
    for k in required:
        credentials._tenant_snapshot[(T1, k)] = "set"
    tenant_view = await tool_config.catalogue(include_values=False, force=False, tenant_id=T1)
    platform_view = await tool_config.catalogue(
        include_values=False, force=False, tenant_id=T1, scope="platform"
    )
    assert tenant_view["scope"] == "tenant" and tenant_view["tenant_id"] == T1
    assert tenant_view["missing_required"] == 0
    assert platform_view["scope"] == "platform"
    assert platform_view["missing_required"] >= 1


# --- router ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_defaults_to_the_tenant_table():
    db = RecordingDB()
    resp = await router.set_value(
        KEY, router.ValueBody(value="sk-new-2222"), scope=None, user=_admin(T1), db=db
    )
    assert resp.status_code == 200
    sql, params = db.statements[0]
    assert "INSERT INTO tenant_tool_credentials" in sql
    assert "ON CONFLICT (tenant_id, key)" in sql
    assert params["tid"] == T1 and params["key"] == KEY
    assert db.commits == 1
    row = _body(resp)["data"]
    assert row["key"] == KEY and row["scope"] == "tenant"


@pytest.mark.asyncio
async def test_patch_platform_scope_writes_platform_settings():
    db = RecordingDB()
    resp = await router.set_value(
        KEY,
        router.ValueBody(value="sk-new-3333", scope="platform"),
        scope=None,
        user=_admin(T1),
        db=db,
    )
    assert resp.status_code == 200
    sql, params = db.statements[0]
    assert "INSERT INTO platform_settings" in sql
    assert params["key"] == credentials.PREFIX + KEY
    assert _body(resp)["data"]["scope"] == "platform"


@pytest.mark.asyncio
async def test_query_scope_is_honoured_and_bad_scope_is_rejected():
    db = RecordingDB()
    resp = await router.set_value(
        KEY, router.ValueBody(value="v"), scope="platform", user=_admin(T1), db=db
    )
    assert "platform_settings" in db.statements[0][0]
    bad = await router.set_value(
        KEY, router.ValueBody(value="v", scope="galaxy"), scope=None, user=_admin(T1), db=db
    )
    assert bad.status_code == 400
    assert len(db.statements) == 1
    listed = await router.list_tool_config(scope="galaxy", user=_admin(T1))
    assert listed.status_code == 400
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_delete_clears_the_chosen_scope_only():
    db = RecordingDB()
    r1 = await router.clear_value(KEY, scope=None, body=None, user=_admin(T1), db=db)
    sql, params = db.statements[0]
    assert sql.startswith("DELETE FROM tenant_tool_credentials")
    assert params == {"tid": T1, "k": KEY}
    r2 = await router.clear_value(
        KEY, scope=None, body=router.ScopeBody(scope="platform"), user=_admin(T1), db=db
    )
    sql2, params2 = db.statements[1]
    assert sql2.startswith("DELETE FROM platform_settings")
    assert params2 == {"k": credentials.PREFIX + KEY}
    assert r1.status_code == 200 and r2.status_code == 200


@pytest.mark.asyncio
async def test_platform_writes_are_audited(caplog):
    db = RecordingDB()
    with caplog.at_level("INFO", logger="abenix.audit.tool_config"):
        await router.set_value(
            KEY,
            router.ValueBody(value="v", scope="platform"),
            scope=None,
            user=_admin(T1),
            db=db,
        )
    line = next(r for r in caplog.records if r.name == "abenix.audit.tool_config")
    msg = line.getMessage()
    assert "scope=platform" in msg and KEY in msg and T1 in msg and "a@x.io" in msg


@pytest.mark.asyncio
async def test_list_returns_the_scope_it_was_asked_for():
    credentials._snapshot[KEY] = "sk-platform-0000"
    credentials._tenant_snapshot[(T1, KEY)] = "sk-tenant-1111"
    tenant = _body(await router.list_tool_config(scope=None, user=_admin(T1)))["data"]
    platform = _body(await router.list_tool_config(scope="platform", user=_admin(T1)))["data"]
    row_t = next(k for g in tenant["groups"] for k in g["keys"] if k["key"] == KEY)
    row_p = next(k for g in platform["groups"] for k in g["keys"] if k["key"] == KEY)
    assert tenant["scope"] == "tenant" and row_t["source"] == "tenant"
    assert platform["scope"] == "platform" and row_p["source"] == "stored"
    assert row_p["tenant_source"] == "tenant"
