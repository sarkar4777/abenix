"""Seed Atlas graphs from YAML files under seeds/atlas/.

Each YAML defines one named graph with typed nodes and labelled edges.
Idempotent — re-runs no-op via stable name match.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models.atlas import AtlasGraph, AtlasNode, AtlasEdge, AtlasNodeKind  # noqa: E402
from models.tenant import Tenant  # noqa: E402
from models.user import User  # noqa: E402

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://abenix:abenix@localhost:5432/abenix",
)
SEEDS_DIR = Path(__file__).parent / "atlas"
SHARED_TENANT_NAME = "Abenix"


async def _shared_tenant_user(db: AsyncSession) -> tuple[Tenant, User]:
    t = (
        await db.execute(select(Tenant).where(Tenant.name == SHARED_TENANT_NAME))
    ).scalar_one_or_none()
    if t is None:
        t = (
            (await db.execute(select(Tenant).order_by(Tenant.created_at)))
            .scalars()
            .first()
        )
    u = (
        (
            await db.execute(
                select(User).where(User.tenant_id == t.id).order_by(User.created_at)
            )
        )
        .scalars()
        .first()
    )
    return t, u


def _kind(value: str | None) -> AtlasNodeKind:
    if not value:
        return AtlasNodeKind.CONCEPT
    try:
        return AtlasNodeKind(value)
    except Exception:
        return AtlasNodeKind.CONCEPT


async def seed_file(
    db: AsyncSession, tenant: Tenant, user: User, spec: dict[str, Any]
) -> None:
    name = spec["name"]
    existing = (
        await db.execute(
            select(AtlasGraph).where(
                AtlasGraph.tenant_id == tenant.id,
                AtlasGraph.name == name,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        print(f"  skip (exists): {name}")
        return
    graph = AtlasGraph(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        owner_user_id=user.id,
        name=name,
        description=spec.get("description", ""),
        version=1,
        node_count=0,
        edge_count=0,
        settings=spec.get("settings", {}),
    )
    db.add(graph)
    await db.flush()

    node_id_map: dict[str, uuid.UUID] = {}
    for n in spec.get("nodes", []):
        node = AtlasNode(
            id=uuid.uuid4(),
            graph_id=graph.id,
            label=n["label"],
            kind=_kind(n.get("kind")),
            description=n.get("description", ""),
            properties=n.get("properties", {}),
            position_x=n.get("x"),
            position_y=n.get("y"),
            source="seed",
            tags=n.get("tags", []),
        )
        db.add(node)
        node_id_map[n["id"]] = node.id

    await db.flush()

    for e in spec.get("edges", []):
        src = node_id_map.get(e["from"])
        dst = node_id_map.get(e["to"])
        if not (src and dst):
            continue
        db.add(
            AtlasEdge(
                id=uuid.uuid4(),
                graph_id=graph.id,
                from_node_id=src,
                to_node_id=dst,
                label=e.get("label", "related_to"),
                description=e.get("description", ""),
                is_directed=e.get("directed", True),
                properties=e.get("properties", {}),
                source="seed",
            )
        )

    graph.node_count = len(spec.get("nodes", []))
    graph.edge_count = len(spec.get("edges", []))
    await db.commit()
    print(f"  seeded {name}: {graph.node_count} nodes, {graph.edge_count} edges")


async def main() -> None:
    engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as db:
        tenant, user = await _shared_tenant_user(db)
        if not SEEDS_DIR.exists():
            print(f"no atlas seeds dir at {SEEDS_DIR}")
            return
        for f in sorted(SEEDS_DIR.glob("*.yaml")):
            print(f"Seeding atlas {f.name} ...")
            try:
                spec = yaml.safe_load(f.read_text(encoding="utf-8"))
            except Exception as ex:
                print(f"  skip ({ex})")
                continue
            await seed_file(db, tenant, user, spec)
    await engine.dispose()
    print("Atlas seed complete.")


if __name__ == "__main__":
    asyncio.run(main())
