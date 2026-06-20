"""Portfolio Schemas API — manage SchemaPortfolioTool schemas dynamically."""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.responses import error, success

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.user import User
from models.portfolio_schema import PortfolioSchema

router = APIRouter(prefix="/api/portfolio-schemas", tags=["portfolio-schemas"])


class CreateSchemaRequest(BaseModel):
    domain_name: str = Field(..., max_length=100, pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(..., max_length=255)
    description: str | None = None
    record_noun: str = "record"
    record_noun_plural: str = "records"
    schema_json: dict = Field(default_factory=dict)


class UpdateSchemaRequest(BaseModel):
    label: str | None = None
    description: str | None = None
    record_noun: str | None = None
    record_noun_plural: str | None = None
    schema_json: dict | None = None
    is_active: bool | None = None


def _serialize(s: PortfolioSchema) -> dict:
    return {
        "id": str(s.id),
        "domain_name": s.domain_name,
        "label": s.label,
        "description": s.description,
        "record_noun": s.record_noun,
        "record_noun_plural": s.record_noun_plural,
        "schema_json": s.schema_json or {},
        "is_active": s.is_active,
        "tool_name": f"portfolio_{s.domain_name}",
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


@router.get("")
async def list_schemas(
    search: str = Query(""),
    is_active: str = Query(""),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """List portfolio schemas for the current tenant."""
    query = select(PortfolioSchema).where(PortfolioSchema.tenant_id == user.tenant_id)
    if search:
        from sqlalchemy import or_

        query = query.where(
            or_(
                PortfolioSchema.domain_name.ilike(f"%{search}%"),
                PortfolioSchema.label.ilike(f"%{search}%"),
            )
        )
    if is_active == "true":
        query = query.where(PortfolioSchema.is_active.is_(True))
    elif is_active == "false":
        query = query.where(PortfolioSchema.is_active.is_(False))
    query = query.order_by(PortfolioSchema.updated_at.desc())
    result = await db.execute(query)
    return success([_serialize(s) for s in result.scalars().all()])


@router.post("")
async def create_schema(
    body: CreateSchemaRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Create a new portfolio schema."""
    # Check for duplicate domain_name in this tenant
    existing = await db.execute(
        select(PortfolioSchema).where(
            PortfolioSchema.tenant_id == user.tenant_id,
            PortfolioSchema.domain_name == body.domain_name,
        )
    )
    if existing.scalar_one_or_none():
        return error(f"Schema '{body.domain_name}' already exists for this tenant", 409)

    schema = PortfolioSchema(
        id=uuid.uuid4(),
        tenant_id=user.tenant_id,
        domain_name=body.domain_name,
        label=body.label,
        description=body.description,
        record_noun=body.record_noun,
        record_noun_plural=body.record_noun_plural,
        schema_json=body.schema_json,
        is_active=True,
        created_by=user.id,
    )
    db.add(schema)
    await db.commit()
    await db.refresh(schema)
    return success(_serialize(schema), status_code=201)


@router.get("/{schema_id}")
async def get_schema(
    schema_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Get a single schema."""
    result = await db.execute(
        select(PortfolioSchema).where(
            PortfolioSchema.id == schema_id,
            PortfolioSchema.tenant_id == user.tenant_id,
        )
    )
    schema = result.scalar_one_or_none()
    if not schema:
        return error("Schema not found", 404)
    return success(_serialize(schema))


@router.put("/{schema_id}")
async def update_schema(
    schema_id: uuid.UUID,
    body: UpdateSchemaRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Update a schema."""
    result = await db.execute(
        select(PortfolioSchema).where(
            PortfolioSchema.id == schema_id,
            PortfolioSchema.tenant_id == user.tenant_id,
        )
    )
    schema = result.scalar_one_or_none()
    if not schema:
        return error("Schema not found", 404)

    if body.label is not None:
        schema.label = body.label
    if body.description is not None:
        schema.description = body.description
    if body.record_noun is not None:
        schema.record_noun = body.record_noun
    if body.record_noun_plural is not None:
        schema.record_noun_plural = body.record_noun_plural
    if body.schema_json is not None:
        schema.schema_json = body.schema_json
    if body.is_active is not None:
        schema.is_active = body.is_active

    await db.commit()
    await db.refresh(schema)
    return success(_serialize(schema))


@router.delete("/{schema_id}")
async def delete_schema(
    schema_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Delete a schema."""
    result = await db.execute(
        select(PortfolioSchema).where(
            PortfolioSchema.id == schema_id,
            PortfolioSchema.tenant_id == user.tenant_id,
        )
    )
    schema = result.scalar_one_or_none()
    if not schema:
        return error("Schema not found", 404)
    await db.delete(schema)
    await db.commit()
    return success({"deleted": True})


@router.get("/templates/list")
async def list_templates() -> JSONResponse:
    """Return generic starter schema templates that users can clone.

    App-specific schemas that reference an app's own tables live behind
    that app's router and the UI is expected to union them with these.
    """
    return success(
        [
            {
                "id": "real_estate",
                "label": "Real Estate Portfolio",
                "description": "Properties with inspections, documents, transactions",
                "schema_json": {
                    "domain": {
                        "name": "real_estate",
                        "label": "Real Estate Portfolio",
                        "record_noun": "property",
                        "record_noun_plural": "properties",
                    },
                    "main_table": {
                        "name": "properties",
                        "user_scope_column": "owner_id",
                        "title_column": "address",
                        "search_columns": ["address", "city"],
                        "list_columns": ["id", "address", "type", "value", "status"],
                        "columns": {
                            "id": {"type": "uuid", "label": "ID"},
                            "address": {"type": "string", "label": "Address"},
                            "type": {"type": "string", "label": "Type"},
                            "value": {
                                "type": "number",
                                "label": "Value",
                                "format": "${:,.0f}",
                            },
                            "status": {"type": "string", "label": "Status"},
                        },
                        "summary_aggregations": {
                            "total": {"sql": "count(*)", "label": "Total properties"},
                            "total_value": {
                                "sql": "sum(value)",
                                "label": "Total portfolio value",
                                "format": "${:,.0f}",
                            },
                        },
                    },
                    "related_tables": [],
                },
            },
            {
                "id": "ma_documents",
                "label": "M&A Document Repository",
                "description": "Deal documents with provisions, parties, dates",
                "schema_json": {
                    "domain": {
                        "name": "ma_documents",
                        "label": "M&A Document Repository",
                        "record_noun": "deal",
                        "record_noun_plural": "deals",
                    },
                    "main_table": {
                        "name": "ma_deals",
                        "user_scope_column": "owner_id",
                        "title_column": "deal_name",
                        "search_columns": ["deal_name", "target_company"],
                        "list_columns": [
                            "id",
                            "deal_name",
                            "deal_type",
                            "deal_value",
                            "status",
                        ],
                        "columns": {
                            "id": {"type": "uuid", "label": "ID"},
                            "deal_name": {"type": "string", "label": "Deal Name"},
                            "deal_type": {"type": "string", "label": "Type"},
                            "deal_value": {
                                "type": "number",
                                "label": "Value",
                                "format": "${:,.0f}",
                            },
                            "status": {"type": "string", "label": "Status"},
                        },
                        "summary_aggregations": {
                            "total": {"sql": "count(*)", "label": "Total deals"},
                        },
                    },
                    "related_tables": [],
                },
            },
        ]
    )
