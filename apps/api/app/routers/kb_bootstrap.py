"""Bootstrap + per-subject collection endpoints for standalone-app integrations."""
from __future__ import annotations

import re
import sys
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.responses import error, success
from app.core.sanitize import sanitize_input

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.agent import Agent  # noqa: E402
from models.collection_grant import (  # noqa: E402
    AgentCollectionGrant,
    CollectionPermission,
    UserCollectionGrant,
)
from models.knowledge_base import KBStatus, KnowledgeBase  # noqa: E402
from models.knowledge_project import (  # noqa: E402
    CollectionVisibility, KnowledgeProject,
)
from models.user import User  # noqa: E402

router = APIRouter(prefix="/api/knowledge-projects", tags=["knowledge-bootstrap"])


_SLUG_RE = re.compile(r"[^a-z0-9-]+")


def _slugify(text: str) -> str:
    s = (text or "").lower().strip()
    s = _SLUG_RE.sub("-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s[:120] or "default"


class BootstrapCollectionSpec(BaseModel):
    """One collection to create inside the bootstrapped project."""
    name: str = Field(..., min_length=1, max_length=255)
    slug: str | None = Field(None, max_length=120)
    description: str = Field("", max_length=2000)
    default_visibility: str = Field(
        "project", pattern="^(private|project|tenant)$",
    )
    vector_backend: str = Field(
        "pinecone", pattern="^(pinecone|pgvector)$",
    )
    # Agents that should be granted access to this collection. Strings
    # are agent slugs (e.g. "st-chat"); resolved at bootstrap time to
    # UUIDs in the same tenant. Unknown slugs are skipped, not errors —
    # bootstrap is "best effort, idempotent".
    agent_slugs: list[str] = Field(default_factory=list)
    agent_permission: str = Field(
        "READ", pattern="^(READ|WRITE|ADMIN)$",
    )


class BootstrapRequest(BaseModel):
    slug: str = Field(..., min_length=1, max_length=120)
    name: str = Field(..., min_length=1, max_length=255)
    description: str = Field("", max_length=2000)
    collections: list[BootstrapCollectionSpec] = Field(default_factory=list)


class EnsureSubjectCollectionRequest(BaseModel):
    """Per-user collection inside a project."""
    subject_type: str = Field(..., min_length=1, max_length=64)
    subject_id: str = Field(..., min_length=1, max_length=120)
    description: str = Field("", max_length=500)
    default_visibility: str = Field(
        "private", pattern="^(private|project|tenant)$",
    )
    vector_backend: str = Field(
        "pinecone", pattern="^(pinecone|pgvector)$",
    )


async def _resolve_agents_by_slug(
    db: AsyncSession, *, tenant_id: uuid.UUID, slugs: list[str],
) -> list[Agent]:
    """Look up agents by slug or by name within the tenant."""
    if not slugs:
        return []
    # Some Agent models call the field `slug`, others `name`. Try both.
    has_slug = hasattr(Agent, "slug")
    if has_slug:
        rows = await db.execute(
            select(Agent).where(
                Agent.tenant_id == tenant_id,
                getattr(Agent, "slug").in_(slugs),
            )
        )
    else:
        rows = await db.execute(
            select(Agent).where(
                Agent.tenant_id == tenant_id,
                Agent.name.in_(slugs),
            )
        )
    return list(rows.scalars().all())


async def _grant_agent(
    db: AsyncSession, *, agent_id: uuid.UUID, collection_id: uuid.UUID,
    permission: CollectionPermission, granted_by: uuid.UUID,
) -> None:
    """Idempotent agent grant — UPSERT semantics."""
    existing = await db.execute(
        select(AgentCollectionGrant).where(
            AgentCollectionGrant.agent_id == agent_id,
            AgentCollectionGrant.collection_id == collection_id,
        )
    )
    g = existing.scalar_one_or_none()
    if g is None:
        db.add(AgentCollectionGrant(
            agent_id=agent_id,
            collection_id=collection_id,
            permission=permission,
            granted_by=granted_by,
        ))
    elif g.permission != permission:
        g.permission = permission
        g.granted_by = granted_by


@router.post("/bootstrap")
async def bootstrap_project(
    body: BootstrapRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Idempotent project bootstrap."""
    slug = _slugify(body.slug)
    name = sanitize_input(body.name)

    # Find-or-create the project. The lookup is by (tenant_id, slug)
    # which is unique-constrained, so the second call is a pure no-op.
    proj = (await db.execute(
        select(KnowledgeProject).where(
            KnowledgeProject.tenant_id == user.tenant_id,
            KnowledgeProject.slug == slug,
        )
    )).scalar_one_or_none()
    if proj is None:
        proj = KnowledgeProject(
            tenant_id=user.tenant_id,
            name=name,
            slug=slug,
            description=sanitize_input(body.description or ""),
            created_by=user.id,
        )
        db.add(proj)
        await db.flush()

    created_collections: list[dict[str, Any]] = []
    skipped_agents: list[str] = []
    for spec in body.collections:
        c_slug = _slugify(spec.slug or spec.name)
        c_name = sanitize_input(spec.name)

        kb = (await db.execute(
            select(KnowledgeBase).where(
                KnowledgeBase.tenant_id == user.tenant_id,
                KnowledgeBase.project_id == proj.id,
                KnowledgeBase.name == c_name,
            )
        )).scalar_one_or_none()
        if kb is None:
            kb = KnowledgeBase(
                tenant_id=user.tenant_id,
                project_id=proj.id,
                name=c_name,
                description=sanitize_input(spec.description or ""),
                default_visibility=CollectionVisibility(spec.default_visibility),
                vector_backend=spec.vector_backend,
                status=KBStatus.READY,
                doc_count=0,
                created_by=user.id,
            )
            db.add(kb)
            await db.flush()

        # Grant each requested agent. Unknown slugs are reported in the
        # response so the caller can debug typos without bootstrap
        # itself failing.
        agents = await _resolve_agents_by_slug(
            db, tenant_id=user.tenant_id, slugs=spec.agent_slugs,
        )
        found_slugs = set()
        for a in agents:
            attr = getattr(a, "slug", None) or a.name
            found_slugs.add(attr)
            await _grant_agent(
                db,
                agent_id=a.id,
                collection_id=kb.id,
                permission=CollectionPermission(spec.agent_permission),
                granted_by=user.id,
            )
        for s in spec.agent_slugs:
            if s not in found_slugs:
                skipped_agents.append(s)

        created_collections.append({
            "id": str(kb.id),
            "name": kb.name,
            "slug": c_slug,
            "agents_granted": list(found_slugs),
        })

    await db.commit()
    await db.refresh(proj)
    return success({
        "project": {
            "id": str(proj.id),
            "slug": proj.slug,
            "name": proj.name,
        },
        "collections": created_collections,
        "skipped_agents": skipped_agents,
    })


@router.post("/{slug}/subject-collections/ensure")
async def ensure_subject_collection(
    slug: str,
    body: EnsureSubjectCollectionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Find-or-create the subject's collection inside a project."""
    proj = (await db.execute(
        select(KnowledgeProject).where(
            KnowledgeProject.tenant_id == user.tenant_id,
            KnowledgeProject.slug == _slugify(slug),
        )
    )).scalar_one_or_none()
    if proj is None:
        return error("Project not found", 404)

    name = f"{body.subject_type}-{body.subject_id}"

    kb = (await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.tenant_id == user.tenant_id,
            KnowledgeBase.project_id == proj.id,
            KnowledgeBase.name == name,
        )
    )).scalar_one_or_none()
    if kb is None:
        kb = KnowledgeBase(
            tenant_id=user.tenant_id,
            project_id=proj.id,
            name=name,
            description=sanitize_input(body.description or ""),
            default_visibility=CollectionVisibility(body.default_visibility),
            vector_backend=body.vector_backend,
            status=KBStatus.READY,
            doc_count=0,
            created_by=user.id,
        )
        db.add(kb)
        await db.flush()

        # Mirror agent grants from sibling collections in the project so
        # the per-user collection inherits whatever agent permissions
        # the project's other collections have.
        sibling_grants = (await db.execute(
            select(AgentCollectionGrant).join(
                KnowledgeBase,
                AgentCollectionGrant.collection_id == KnowledgeBase.id,
            ).where(
                KnowledgeBase.project_id == proj.id,
                KnowledgeBase.id != kb.id,
            )
        )).scalars().all()
        seen: set[uuid.UUID] = set()
        for g in sibling_grants:
            if g.agent_id in seen:
                continue
            seen.add(g.agent_id)
            await _grant_agent(
                db,
                agent_id=g.agent_id,
                collection_id=kb.id,
                permission=g.permission,
                granted_by=user.id,
            )

    await db.commit()
    await db.refresh(kb)
    return success({
        "id": str(kb.id),
        "name": kb.name,
        "project_id": str(proj.id),
        "project_slug": proj.slug,
    })
