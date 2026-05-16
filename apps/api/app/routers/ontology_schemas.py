"""Ontology Schema CRUD + project activation."""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.permissions import features_for, is_admin
from app.core.responses import error, success
from app.core.sanitize import sanitize_input

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.knowledge_base import KnowledgeBase  # noqa: E402
from models.knowledge_project import KnowledgeProject  # noqa: E402
from models.ontology_schema import OntologySchema  # noqa: E402
from models.user import User  # noqa: E402

router = APIRouter(
    prefix="/api/knowledge-projects",
    tags=["knowledge-ontology"],
)


class EntityTypeSpec(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: str = Field("", max_length=500)
    synonyms: list[str] = Field(default_factory=list)


class RelationshipTypeSpec(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: str = Field("", max_length=500)
    source_types: list[str] = Field(default_factory=list)
    target_types: list[str] = Field(default_factory=list)


class CreateSchemaRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str = Field("", max_length=2000)
    entity_types: list[EntityTypeSpec] = Field(default_factory=list)
    relationship_types: list[RelationshipTypeSpec] = Field(default_factory=list)


def _serialize(s: OntologySchema) -> dict[str, Any]:
    return {
        "id": str(s.id),
        "project_id": str(s.project_id),
        "version": s.version,
        "name": s.name,
        "description": s.description,
        "entity_types": s.entity_types or [],
        "relationship_types": s.relationship_types or [],
        "created_by": str(s.created_by) if s.created_by else None,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }


async def _can_author_ontology(
    db: AsyncSession,
    *,
    user: User,
    project: KnowledgeProject,
) -> bool:
    """Author ontology if any of:"""
    if is_admin(user):
        return True
    if project.created_by == user.id:
        return True
    feats = features_for(user)
    if feats.get("manage_ontology", False):
        return True
    # KB v2 deviation fix — honour per-project membership grants.
    from app.services.project_access import assert_project_role
    from models.project_member import ProjectRole

    return await assert_project_role(
        db,
        user_id=user.id,
        project_id=project.id,
        minimum_role=ProjectRole.EDIT,
    )


async def _load_project(
    db: AsyncSession,
    *,
    project_id: uuid.UUID,
    tenant_id: uuid.UUID,
) -> KnowledgeProject | None:
    p = await db.get(KnowledgeProject, project_id)
    if p is None or p.tenant_id != tenant_id:
        return None
    return p


@router.get("/{project_id}/ontology-schemas")
async def list_schemas(
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    p = await _load_project(db, project_id=project_id, tenant_id=user.tenant_id)
    if p is None:
        return error("Project not found", 404)
    rows = (
        (
            await db.execute(
                select(OntologySchema)
                .where(
                    OntologySchema.project_id == project_id,
                )
                .order_by(desc(OntologySchema.version))
            )
        )
        .scalars()
        .all()
    )
    return success([_serialize(s) for s in rows])


@router.get("/{project_id}/ontology-schemas/active")
async def get_active_schema(
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    p = await _load_project(db, project_id=project_id, tenant_id=user.tenant_id)
    if p is None:
        return error("Project not found", 404)
    if p.ontology_schema_id is None:
        return success(None)
    s = await db.get(OntologySchema, p.ontology_schema_id)
    return success(_serialize(s) if s else None)


@router.post("/{project_id}/ontology-schemas")
async def create_schema(
    project_id: uuid.UUID,
    body: CreateSchemaRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    p = await _load_project(db, project_id=project_id, tenant_id=user.tenant_id)
    if p is None:
        return error("Project not found", 404)
    if not await _can_author_ontology(db, user=user, project=p):
        return error("Forbidden — manage_ontology permission required", 403)

    # Auto-version: next version = max(version) + 1, defaulting to 1.
    last_version = await db.scalar(
        select(OntologySchema.version)
        .where(OntologySchema.project_id == project_id)
        .order_by(desc(OntologySchema.version))
        .limit(1)
    )
    next_version = (last_version or 0) + 1

    s = OntologySchema(
        project_id=project_id,
        version=next_version,
        name=sanitize_input(body.name),
        description=sanitize_input(body.description or ""),
        entity_types=[t.model_dump() for t in body.entity_types],
        relationship_types=[t.model_dump() for t in body.relationship_types],
        created_by=user.id,
    )
    db.add(s)
    await db.flush()

    # Auto-activate the newly-created schema if the project has no
    # active one yet — the natural intent on first create.
    if p.ontology_schema_id is None:
        p.ontology_schema_id = s.id
    await db.commit()
    await db.refresh(s)
    return success(_serialize(s), status_code=201)


@router.post("/{project_id}/ontology-schemas/{schema_id}/activate")
async def activate_schema(
    project_id: uuid.UUID,
    schema_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    p = await _load_project(db, project_id=project_id, tenant_id=user.tenant_id)
    if p is None:
        return error("Project not found", 404)
    if not await _can_author_ontology(db, user=user, project=p):
        return error("Forbidden — manage_ontology permission required", 403)

    s = await db.get(OntologySchema, schema_id)
    if s is None or s.project_id != project_id:
        return error("Schema not found in this project", 404)

    p.ontology_schema_id = s.id
    await db.commit()
    return success({"active_schema_id": str(s.id), "version": s.version})


@router.get("/{project_id}/correlations")
async def list_top_correlations(
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Top-N entity correlations across the project's collections."""
    p = await _load_project(db, project_id=project_id, tenant_id=user.tenant_id)
    if p is None:
        return error("Project not found", 404)

    # Pull collection ids in this project, then query graph_entities
    # for the top entities by mention_count. Bounded at 25 — this is
    # the "what's in this project at a glance" fast path.
    coll_rows = (
        await db.execute(
            select(KnowledgeBase.id).where(
                KnowledgeBase.project_id == project_id,
            )
        )
    ).all()
    coll_ids = [r[0] for r in coll_rows]
    if not coll_ids:
        return success([])

    # Fall back to a lightweight raw SQL for the cross-collection
    # entity scan — keeps the v1 schema (kb_id) compatible.
    from sqlalchemy import text as _t

    rows = (await db.execute(_t("""
        SELECT canonical_name, entity_type, SUM(mention_count) AS mentions,
               COUNT(DISTINCT kb_id) AS collections
        FROM graph_entities
        WHERE kb_id = ANY(:coll_ids)
        GROUP BY canonical_name, entity_type
        ORDER BY mentions DESC
        LIMIT 25
        """).bindparams(coll_ids=coll_ids))).all()

    return success(
        [
            {
                "name": r[0],
                "type": r[1],
                "mentions": int(r[2] or 0),
                "collections": int(r[3] or 0),
            }
            for r in rows
        ]
    )


@router.get("/{project_id}/correlations/{entity_name}")
async def correlate_entity(
    project_id: uuid.UUID,
    entity_name: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Co-occurring entities for one canonical entity name."""
    p = await _load_project(db, project_id=project_id, tenant_id=user.tenant_id)
    if p is None:
        return error("Project not found", 404)
    coll_rows = (
        await db.execute(
            select(KnowledgeBase.id).where(
                KnowledgeBase.project_id == project_id,
            )
        )
    ).all()
    coll_ids = [r[0] for r in coll_rows]
    if not coll_ids:
        return success({"entity": entity_name, "related": []})

    # Find the entity row; pull its source_doc_ids; find other entities
    # that share at least one of those doc ids. JSONB ?| operator does
    # the array intersection in one query.
    from sqlalchemy import text as _t

    target = (
        await db.execute(
            _t(
                "SELECT id, source_doc_ids, mention_count "
                "FROM graph_entities "
                "WHERE kb_id = ANY(:coll_ids) AND canonical_name = :name "
                "ORDER BY mention_count DESC LIMIT 1"
            ).bindparams(coll_ids=coll_ids, name=entity_name)
        )
    ).first()
    if target is None:
        return error("Entity not found in this project", 404)

    # Skip if no source docs recorded (older rows pre-lineage may be
    # null; we degrade gracefully to empty rather than 500).
    src = target[1] or []
    if not isinstance(src, list) or not src:
        return success({"entity": entity_name, "related": []})

    related = (
        await db.execute(
            _t("""
        SELECT canonical_name, entity_type, mention_count,
               cardinality(ARRAY(
                 SELECT jsonb_array_elements_text(source_doc_ids)
                 INTERSECT SELECT jsonb_array_elements_text(CAST(:src AS jsonb))
               )) AS shared_docs
        FROM graph_entities
        WHERE kb_id = ANY(:coll_ids)
          AND canonical_name <> :name
          AND source_doc_ids ?| ARRAY(
            SELECT jsonb_array_elements_text(CAST(:src AS jsonb))
          )
        ORDER BY shared_docs DESC, mention_count DESC
        LIMIT 25
        """).bindparams(
                coll_ids=coll_ids, name=entity_name, src=__import__("json").dumps(src)
            )
        )
    ).all()

    return success(
        {
            "entity": entity_name,
            "type": target[2] if len(target) > 2 else None,
            "related": [
                {
                    "name": r[0],
                    "type": r[1],
                    "mentions": int(r[2] or 0),
                    "shared_documents": int(r[3] or 0),
                }
                for r in related
            ],
        }
    )
