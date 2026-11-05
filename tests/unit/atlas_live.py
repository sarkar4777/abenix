"""The Atlas router against real Postgres, with auth replaced and nothing else."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from kb_pg import make_kb, make_tenant


def _async_url(url: str) -> str:
    return url.replace("postgresql://", "postgresql+asyncpg://")


def make_user(cur, tenant: str, role: str = "ADMIN") -> SimpleNamespace:
    from models.user import UserRole

    uid = str(uuid.uuid4())
    cur.execute(
        "INSERT INTO users (id, tenant_id, email, password_hash, full_name, role, is_active, "
        "stripe_connect_onboarded, tokens_used_this_month, cost_used_this_month) "
        "VALUES (%s, %s, %s, 'x', 'Tester', %s, true, false, 0, 0)",
        (uid, tenant, f"{uid}@test.io", role),
    )
    return SimpleNamespace(
        id=uuid.UUID(uid),
        tenant_id=uuid.UUID(tenant),
        role=getattr(UserRole, role),
        email=f"{uid}@test.io",
        full_name="Tester",
    )


def app_for(url: str, user: SimpleNamespace):
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )

    from sqlalchemy.pool import NullPool

    from app.core.deps import get_current_user, get_db
    from app.routers import atlas

    engine = create_async_engine(_async_url(url), poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def db():
        async with factory() as session:
            yield session

    app = FastAPI()
    app.include_router(atlas.router)
    app.dependency_overrides[get_db] = db
    app.dependency_overrides[get_current_user] = lambda: user
    return app, engine, factory


def client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://atlas", timeout=120
    )


def bulk_graph(
    cur, tenant: str, user, nodes: int, edges: int, kb: str | None = None
) -> str:
    """A synthetic graph written straight to the tables, laid out on a grid."""
    gid = str(uuid.uuid4())
    cur.execute(
        "INSERT INTO atlas_graphs (id, tenant_id, owner_user_id, name, description, kb_id, "
        "version, node_count, edge_count, settings) "
        "VALUES (%s, %s, %s, 'big', '', %s, 1, %s, %s, '{}')",
        (gid, tenant, str(user.id), kb, nodes, edges),
    )
    cols = max(1, int(nodes**0.5))
    cur.execute(
        f"""
        INSERT INTO atlas_nodes (id, graph_id, label, kind, description, properties,
            position_x, position_y, source, tags, recorded_at, created_at, updated_at)
        SELECT gen_random_uuid(), %s, 'Node ' || i, 'concept', 'synthetic node ' || i, '{{}}',
            80 + (i %% {cols}) * 240, 80 + (i / {cols}) * 180, 'user', '[]', now(),
            now() + i * interval '1 microsecond', now()
        FROM generate_series(0, %s - 1) i
        """,
        (gid, nodes),
    )
    cur.execute("ANALYZE atlas_nodes")
    cur.execute(
        """
        INSERT INTO atlas_edges (id, graph_id, from_node_id, to_node_id, label, description,
            is_directed, properties, source, recorded_at, created_at, updated_at)
        SELECT gen_random_uuid(), %s, a.id, b.id, 'related_to', '', true, '{}', 'user', now(), now(), now()
        FROM (SELECT id, row_number() OVER (ORDER BY created_at) AS r
              FROM atlas_nodes WHERE graph_id = %s) a
        CROSS JOIN generate_series(1, 4) m
        JOIN (SELECT id, row_number() OVER (ORDER BY created_at) AS r
              FROM atlas_nodes WHERE graph_id = %s) b
          ON b.r = (a.r * (5 + 2 * m) + m) %% %s + 1
        WHERE a.id <> b.id
        LIMIT %s
        """,
        (gid, gid, gid, nodes, edges),
    )
    cur.execute("ANALYZE atlas_nodes")
    cur.execute("ANALYZE atlas_edges")
    return gid


@pytest.fixture
def atlas_world(kg_conn, kg_db_url):
    cur = kg_conn.cursor()
    tenant = make_tenant(cur)
    user = make_user(cur, tenant)
    kb = make_kb(cur, tenant, created_by=str(user.id))
    app, engine, factory = app_for(kg_db_url, user)
    yield SimpleNamespace(
        cur=cur,
        tenant=tenant,
        user=user,
        kb=kb,
        app=app,
        engine=engine,
        factory=factory,
    )
