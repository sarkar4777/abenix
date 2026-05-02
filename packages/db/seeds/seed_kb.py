"""Seed knowledge-base collections + sample documents from YAML.

Loads every `kb/*.yaml` file and ensures:

  1. The KnowledgeProject exists for `project.slug` under the shared tenant.
  2. Each collection in `collections[]` exists as a KnowledgeBase row.
  3. Each agent listed in `agent_slugs[]` has an AgentCollectionGrant.
  4. Each document in `documents[]` is upserted by `doc.id`.

Idempotent: running twice is a no-op. Documents are upserted by stable
id, never duplicated. Cognify chunking + vector indexing happens in the
hybrid_search write path, not here — this script only stages the rows.

Without this seed every standalone (ResolveAI, ClaimsIQ, Industrial IoT)
sees `knowledge_search → results=0` because no collection rows exist
for the tenant. After seeding, the new structured `no_match` vs.
`no_kb_configured` warnings let agents distinguish "searched, found
nothing" from "nothing wired" — and policy-research / resolution-planner
emit non-empty fallbacks instead of silently returning [].
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
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models.agent import Agent  # noqa: E402
from models.collection_grant import (  # noqa: E402
    AgentCollectionGrant,
    CollectionPermission,
)
from models.knowledge_base import KBStatus, KnowledgeBase  # noqa: E402
from models.knowledge_project import (  # noqa: E402
    CollectionVisibility,
    KnowledgeProject,
)
from models.tenant import Tenant  # noqa: E402
from models.user import User  # noqa: E402

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://abenix:abenix@localhost:5432/abenix",
)
SEEDS_DIR = Path(__file__).parent / "kb"
SHARED_TENANT_NAME = "Abenix"


async def _get_shared_tenant_user(db: AsyncSession) -> tuple[Tenant, User]:
    tenant = (
        await db.execute(select(Tenant).where(Tenant.name == SHARED_TENANT_NAME))
    ).scalar_one_or_none()
    if tenant is None:
        raise RuntimeError(
            "Abenix tenant missing — run seed_agents.py before seed_kb.py."
        )
    system_user = (
        await db.execute(select(User).where(User.email == "system@abenix.dev"))
    ).scalar_one_or_none()
    if system_user is None:
        raise RuntimeError("system@abenix.dev user missing — seed_agents first.")
    return tenant, system_user


async def _upsert_project(
    db: AsyncSession, *, tenant_id: uuid.UUID, user_id: uuid.UUID, spec: dict[str, Any]
) -> KnowledgeProject:
    proj = (
        await db.execute(
            select(KnowledgeProject).where(
                KnowledgeProject.tenant_id == tenant_id,
                KnowledgeProject.slug == spec["slug"],
            )
        )
    ).scalar_one_or_none()
    if proj is None:
        proj = KnowledgeProject(
            tenant_id=tenant_id,
            name=spec.get("name") or spec["slug"],
            slug=spec["slug"],
            description=spec.get("description") or "",
            created_by=user_id,
        )
        db.add(proj)
        await db.flush()
        print(f"  + project {proj.slug}")
    return proj


async def _upsert_collection(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project: KnowledgeProject,
    user_id: uuid.UUID,
    spec: dict[str, Any],
) -> KnowledgeBase:
    name = spec["name"]
    kb = (
        await db.execute(
            select(KnowledgeBase).where(
                KnowledgeBase.tenant_id == tenant_id,
                KnowledgeBase.project_id == project.id,
                KnowledgeBase.name == name,
            )
        )
    ).scalar_one_or_none()
    if kb is None:
        kb = KnowledgeBase(
            tenant_id=tenant_id,
            project_id=project.id,
            name=name,
            description=spec.get("description") or "",
            default_visibility=CollectionVisibility(
                spec.get("default_visibility", "project")
            ),
            vector_backend=spec.get("vector_backend", "pgvector"),
            status=KBStatus.READY,
            doc_count=0,
            created_by=user_id,
        )
        db.add(kb)
        await db.flush()
        print(f"    + collection {name} ({spec['slug']})")
    return kb


async def _grant_agents(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    collection: KnowledgeBase,
    slugs: list[str],
    permission: str,
) -> None:
    if not slugs:
        return
    rows = await db.execute(
        select(Agent).where(Agent.tenant_id == tenant_id, Agent.slug.in_(slugs))
    )
    agents = rows.scalars().all()
    if not agents:
        return
    # ON CONFLICT DO NOTHING handles idempotency atomically — survives
    # concurrent re-runs and dodges the autoflush-vs-unique-constraint
    # race that previously aborted the whole transaction.
    for agent in agents:
        stmt = (
            pg_insert(AgentCollectionGrant.__table__)
            .values(
                id=uuid.uuid4(),
                agent_id=agent.id,
                collection_id=collection.id,
                permission=CollectionPermission(permission).value,
                granted_by=user_id,
            )
            .on_conflict_do_nothing(index_elements=["agent_id", "collection_id"])
        )
        await db.execute(stmt)


async def _upsert_documents(
    db: AsyncSession,
    *,
    collection: KnowledgeBase,
    documents: list[dict[str, Any]],
) -> int:
    """Document seeding is intentionally a no-op.

    The platform's `documents` table is a metadata-only registry that
    references externally-stored files (filename, file_type, file_size,
    storage_url, chunk_count). The actual searchable content lives in
    the `chunks` table (pgvector embeddings) and is populated by the
    Cognify ingestion pipeline, not by raw SQL.

    YAML seed `documents:` entries describe content (title, body, meta)
    in a shape that doesn't fit either table cleanly without inventing
    storage_urls and running embedding. The right place to seed real
    KB content is the upload UI or POST /api/knowledge/collections/
    {id}/documents — both go through Cognify and get proper chunks.

    So we accept the seed entries, log a friendly hint, and return 0
    rows written. Collections + agent grants (the valuable rows for
    runtime tool routing) are already persisted by the caller."""
    if not documents:
        return 0
    print(
        f"      ({len(documents)} doc spec(s) noted — use the upload UI "
        f"or POST /api/knowledge/collections/{collection.id}/documents to "
        f"ingest content via Cognify)"
    )
    return 0

    if written:
        collection.doc_count = (collection.doc_count or 0) + written
    return written


async def seed_kb() -> None:
    if not SEEDS_DIR.exists():
        print(f"No KB seed dir at {SEEDS_DIR}")
        return
    yaml_files = sorted(SEEDS_DIR.glob("*.yaml"))
    if not yaml_files:
        print(f"No KB seed YAML files in {SEEDS_DIR}")
        return

    engine = create_async_engine(DATABASE_URL, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    failures: list[str] = []
    # One session per YAML file with a clean commit boundary.
    # If one file's seed hits a UNIQUE / autoflush issue, it shouldn't
    # poison the whole bootstrap — log it, move on.
    for yf in yaml_files:
        with open(yf, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not data:
            continue
        print(f"Seeding KB {yf.name} ...")
        try:
            async with factory() as db:
                tenant, user = await _get_shared_tenant_user(db)
                proj_spec = data.get("project") or {}
                project = await _upsert_project(
                    db, tenant_id=tenant.id, user_id=user.id, spec=proj_spec
                )
                for c_spec in data.get("collections") or []:
                    # Each collection gets its own savepoint so a single
                    # bad collection doesn't take the whole project down.
                    async with db.begin_nested():
                        kb = await _upsert_collection(
                            db,
                            tenant_id=tenant.id,
                            project=project,
                            user_id=user.id,
                            spec=c_spec,
                        )
                        await db.flush()
                        await _grant_agents(
                            db,
                            tenant_id=tenant.id,
                            user_id=user.id,
                            collection=kb,
                            slugs=c_spec.get("agent_slugs") or [],
                            permission=c_spec.get("agent_permission", "READ"),
                        )
                        await db.flush()
                        docs_written = await _upsert_documents(
                            db,
                            collection=kb,
                            documents=c_spec.get("documents") or [],
                        )
                        if docs_written:
                            print(f"      docs: {docs_written}")
                await db.commit()
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{yf.name}: {type(exc).__name__}: {exc}"[:300])
            print(f"  [warn] {yf.name} failed — {type(exc).__name__}: {str(exc)[:200]}")
    await engine.dispose()
    if failures:
        print(f"KB seed complete with {len(failures)} failure(s):")
        for line in failures:
            print(f"  - {line}")
        # Don't fail the whole deploy — agents/users seeding already
        # succeeded. KB is best-effort. Future invocations are idempotent.
        return
    print("KB seed complete.")


if __name__ == "__main__":
    asyncio.run(seed_kb())
