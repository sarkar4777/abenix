"""Portfolio Schemas API — manage SchemaPortfolioTool schemas dynamically."""

from __future__ import annotations

import copy
import json
import logging
import sys
import uuid
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import portfolio_import as pi
from app.core.deps import get_current_user, get_db
from app.core.portfolio_schema_check import load_template, validate_portfolio_schema
from app.core.responses import error, success

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.agent import Agent, AgentStatus
from models.user import User
from models.portfolio_schema import PortfolioSchema

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/portfolio-schemas", tags=["portfolio-schemas"])


class CreateSchemaRequest(BaseModel):
    domain_name: str = Field(..., max_length=100, pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    record_noun: str = "record"
    record_noun_plural: str = "records"
    schema_json: dict = Field(default_factory=dict)


class UpdateSchemaRequest(BaseModel):
    label: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    record_noun: str | None = None
    record_noun_plural: str | None = None
    schema_json: dict | None = None
    is_active: bool | None = None


def _invalid(problems: list[str]) -> JSONResponse:
    more = f" (and {len(problems) - 5} more)" if len(problems) > 5 else ""
    return error(
        "Schema is not valid: " + "; ".join(problems[:5]) + more,
        422,
        error_code="INVALID_PORTFOLIO_SCHEMA",
        details={"problems": problems},
    )


async def _agents_using(
    db: AsyncSession, tenant_id: uuid.UUID, tool_name: str
) -> list[dict]:
    rows = await db.execute(
        select(Agent.id, Agent.name, Agent.slug).where(
            Agent.tenant_id == tenant_id,
            Agent.status != AgentStatus.ARCHIVED,
            Agent.model_config_["tools"].contains([tool_name]),
        )
    )
    return [{"id": str(r.id), "name": r.name, "slug": r.slug} for r in rows.all()]


def _serialize(s: PortfolioSchema, my_rows: int | None = None) -> dict:
    table = pi.schema_source_table(s.schema_json)
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
        "source": "spreadsheet" if table else "manual",
        "table_name": table
        or ((s.schema_json or {}).get("main_table") or {}).get("name"),
        "my_rows": my_rows,
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
    schemas = list(result.scalars().all())
    counts = await _my_row_counts(db, user, schemas)
    return success([_serialize(s, counts.get(s.id)) for s in schemas])


async def _my_row_counts(db: AsyncSession, user: User, schemas: list) -> dict:
    """Rows the caller owns in each spreadsheet-made table, a missing table counts as None."""
    tables = {
        s.id: t
        for s in schemas
        if (t := pi.schema_source_table(s.schema_json))
        and pi.is_import_table(t, user.tenant_id, s.domain_name)
    }
    if not tables:
        return {}
    try:
        present = {
            r[0]
            for r in (
                await db.execute(
                    text(
                        "SELECT relname FROM pg_class WHERE relkind = 'r' AND relname = ANY(:names)"
                    ),
                    {"names": sorted(set(tables.values()))},
                )
            ).all()
        }
        out = {}
        for sid, t in tables.items():
            if t in present:
                out[sid] = await pi.count_owner_rows(db, t, user.id)
        return out
    except Exception as e:
        logger.warning("portfolio row counts failed: %s", e)
        await db.rollback()
        return {}


@router.post("")
async def create_schema(
    body: CreateSchemaRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Create a new portfolio schema."""
    existing = await db.execute(
        select(PortfolioSchema).where(
            PortfolioSchema.tenant_id == user.tenant_id,
            PortfolioSchema.domain_name == body.domain_name,
        )
    )
    if existing.scalar_one_or_none():
        return error(f"Schema '{body.domain_name}' already exists for this tenant", 409)

    label = body.label.strip()
    if not label:
        return _invalid(["label must not be blank"])
    schema_json, problems = await validate_portfolio_schema(
        db,
        body.schema_json,
        body.domain_name,
        label=label,
        record_noun=body.record_noun,
        record_noun_plural=body.record_noun_plural,
    )
    if problems:
        return _invalid(problems)

    schema = PortfolioSchema(
        id=uuid.uuid4(),
        tenant_id=user.tenant_id,
        domain_name=body.domain_name,
        label=label,
        description=body.description,
        record_noun=body.record_noun,
        record_noun_plural=body.record_noun_plural,
        schema_json=schema_json,
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
    """Update a schema. The domain name never changes, it is the tool name."""
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
        if not body.label.strip():
            return _invalid(["label must not be blank"])
        schema.label = body.label.strip()
    if body.description is not None:
        schema.description = body.description
    if body.record_noun is not None:
        schema.record_noun = body.record_noun
    if body.record_noun_plural is not None:
        schema.record_noun_plural = body.record_noun_plural
    if body.schema_json is not None:
        schema_json, problems = await validate_portfolio_schema(
            db,
            body.schema_json,
            schema.domain_name,
            label=schema.label,
            record_noun=schema.record_noun,
            record_noun_plural=schema.record_noun_plural,
        )
        if problems:
            return _invalid(problems)
        schema.schema_json = schema_json
    if body.is_active is not None:
        schema.is_active = body.is_active

    await db.commit()
    await db.refresh(schema)
    return success(_serialize(schema))


@router.delete("/{schema_id}")
async def delete_schema(
    schema_id: uuid.UUID,
    force: bool = Query(False),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    drop_table: Annotated[bool, Query()] = False,
) -> JSONResponse:
    """Delete a schema, refusing while agents use it unless force, drop_table also drops its pf_ table."""
    result = await db.execute(
        select(PortfolioSchema).where(
            PortfolioSchema.id == schema_id,
            PortfolioSchema.tenant_id == user.tenant_id,
        )
    )
    schema = result.scalar_one_or_none()
    if not schema:
        return error("Schema not found", 404)
    tool_name = f"portfolio_{schema.domain_name}"
    if not force:
        agents = await _agents_using(db, user.tenant_id, tool_name)
        if agents:
            names = ", ".join(a["name"] for a in agents[:5])
            more = f" and {len(agents) - 5} more" if len(agents) > 5 else ""
            return error(
                f"{len(agents)} agent(s) still use {tool_name}: {names}{more}. "
                "Remove the tool from them first, or delete with force=true.",
                409,
                error_code="PORTFOLIO_SCHEMA_IN_USE",
                details={"agents": agents},
            )
    dropped = None
    table = pi.schema_source_table(getattr(schema, "schema_json", None))
    if drop_table and table:
        if not pi.is_import_table(table, user.tenant_id, schema.domain_name):
            return error(
                f"{table} was not created by a spreadsheet import, so it is left in place.",
                400,
                error_code="PORTFOLIO_TABLE_NOT_OURS",
            )
        others = await _schemas_reading(db, user.tenant_id, table, exclude=schema.id)
        if others:
            return error(
                f"{table} is also read by {', '.join(others)}. Delete those schemas first or keep the table.",
                409,
                error_code="PORTFOLIO_TABLE_SHARED",
            )
        state = await pi.table_state(db, table, user.tenant_id)
        if state["exists"] and not state["ours"]:
            return error(
                f"{table} was not created by a spreadsheet import, so it is left in place.",
                400,
                error_code="PORTFOLIO_TABLE_NOT_OURS",
            )
        if state["exists"]:
            await pi.drop_table(db, table)
            dropped = table
    await db.delete(schema)
    await db.commit()
    return success({"deleted": True, "dropped_table": dropped})


async def _schemas_reading(
    db: AsyncSession, tenant_id: uuid.UUID, table: str, exclude: uuid.UUID
) -> list[str]:
    rows = await db.execute(
        select(
            PortfolioSchema.id, PortfolioSchema.label, PortfolioSchema.schema_json
        ).where(PortfolioSchema.tenant_id == tenant_id)
    )
    names = []
    for sid, label, sj in rows.all():
        if sid == exclude or not isinstance(sj, dict):
            continue
        tables = {(sj.get("main_table") or {}).get("name")}
        tables |= {
            r.get("name") for r in sj.get("related_tables") or [] if isinstance(r, dict)
        }
        if table in tables:
            names.append(label)
    return names


_EXAMPLE_NOTE = (
    " Example only: the {table} table does not ship with the platform, so point"
    " main_table and related_tables at your own tables before saving."
)


@router.get("/templates/list")
async def list_templates() -> JSONResponse:
    """Starter schemas to clone. Each must point at real tables before it will save."""
    templates = [
        {
            "id": "real_estate",
            "label": "Real Estate Portfolio",
            "description": "Properties with inspections, documents, transactions."
            + _EXAMPLE_NOTE.format(table="properties"),
            "requires_own_tables": True,
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
            "description": "Deal documents with provisions, parties, dates."
            + _EXAMPLE_NOTE.format(table="ma_deals"),
            "requires_own_tables": True,
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
    try:
        energy = load_template("energy_contracts")
        energy["description"] = (
            energy.get("description", "").rstrip(".")
            + ". Saves only where ContractIQ has created its contractiq_* tables"
            " in the platform database."
        )
        energy["requires_own_tables"] = True
        templates.append(energy)
    except (OSError, ValueError):
        pass
    return success(templates)


# bring your own data: spreadsheet import


class ImportPlan(BaseModel):
    domain_name: str = Field(
        ..., min_length=1, max_length=50, pattern=r"^[a-z][a-z0-9_]*$"
    )
    label: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(None, max_length=2000)
    record_noun: str = Field("record", min_length=1, max_length=50)
    record_noun_plural: str = Field("records", min_length=1, max_length=50)
    title_column: str | None = None
    columns: list[dict] = Field(default_factory=list)
    mode: Literal["create", "replace", "append"] = "create"


_PLAN_FIELDS = {
    "domain_name": "Domain name must start with a letter and use only lowercase letters, digits and underscores (at most 50)",
    "label": "Give the schema a name (at most 255 characters)",
    "record_noun": "Say what one row is, for example trade (at most 50 characters)",
    "record_noun_plural": "Say what several rows are, for example trades (at most 50 characters)",
    "mode": "Choose create, replace or append",
}

SAMPLE_DOMAIN = "energy_trading_book"


def _sheet_error(e: pi.SpreadsheetError) -> JSONResponse:
    return error(e.message, e.status, error_code=e.code, details=e.details or None)


async def _read_upload(file: UploadFile) -> pi.Sheet:
    data = await file.read(pi.MAX_BYTES + 1)
    return pi.read_sheet(file.filename or "upload.csv", data)


def _parse_plan(raw: str) -> ImportPlan:
    try:
        payload = json.loads(raw)
    except ValueError as e:
        raise pi.SpreadsheetError(
            "The import settings could not be read. Reload the page and try again.", 400
        ) from e
    try:
        return ImportPlan.model_validate(payload)
    except ValidationError as e:
        msgs = []
        for err in e.errors():
            key = str(err["loc"][0]) if err.get("loc") else ""
            msgs.append(_PLAN_FIELDS.get(key, f"{key}: {err['msg']}"))
        raise pi.SpreadsheetError(
            ". ".join(dict.fromkeys(msgs)) + ".", 422, "SPREADSHEET_PLAN_INVALID"
        ) from e


async def _find_schema(
    db: AsyncSession, tenant_id: uuid.UUID, domain: str
) -> PortfolioSchema | None:
    res = await db.execute(
        select(PortfolioSchema).where(
            PortfolioSchema.tenant_id == tenant_id,
            PortfolioSchema.domain_name == domain,
        )
    )
    return res.scalar_one_or_none()


def _reconcile(
    sheet: pi.Sheet, columns: list[dict], existing: dict
) -> tuple[list[dict], list[str]]:
    """Use the stored type for columns the table already has, return the new ones and notes."""
    notes, new_cols = [], []
    for col in columns:
        if col["name"] not in existing:
            new_cols.append(col)
            continue
        typ, has_time = existing[col["name"]]
        if typ != col["type"]:
            notes.append(
                f"{col['label']} is stored as {typ} in the existing table, so its values were read as {typ}."
            )
            col["type"] = typ
        col["has_time"] = has_time
        if typ == "date":
            col["date_order"] = pi.date_order_of(sheet, col["index"])
    return new_cols, notes


async def _run_import(
    db: AsyncSession, user: User, sheet: pi.Sheet, plan: ImportPlan
) -> dict:
    domain = plan.domain_name
    label = plan.label.strip()
    if not label:
        raise pi.SpreadsheetError("Give the schema a name.")
    table = pi.table_name_for(user.tenant_id, domain)
    existing = await _find_schema(db, user.tenant_id, domain)
    columns, title = pi.resolve_plan(sheet, plan.columns, plan.title_column)
    state = await pi.table_state(db, table, user.tenant_id)
    notes: list[str] = []

    if plan.mode == "create":
        if existing:
            raise pi.SpreadsheetError(
                f"There is already a schema called {domain}. Pick another domain name, "
                "or open that schema and use Add rows to replace or append to it.",
                409,
                "PORTFOLIO_SCHEMA_EXISTS",
            )
        if state["exists"] and not state["ours"]:
            raise pi.SpreadsheetError(
                f"A table named {table} already exists and was not made by a spreadsheet import. Pick another domain name.",
                409,
                "PORTFOLIO_TABLE_EXISTS",
            )
        if state["exists"]:
            notes.append(
                f"Reused the table {table} kept from an earlier schema. Your old rows in it were replaced."
            )
    else:
        if not existing:
            raise pi.SpreadsheetError(
                f"There is no schema called {domain} yet. Create it from the spreadsheet first.",
                404,
                "PORTFOLIO_SCHEMA_MISSING",
            )
        if (
            pi.schema_source_table(existing.schema_json) != table
            or not state["exists"]
            or not state["ours"]
        ):
            raise pi.SpreadsheetError(
                f"{existing.label} was not created from a spreadsheet, or its table is gone, so rows cannot be added to it here.",
                409,
                "PORTFOLIO_NOT_IMPORTED",
            )

    new_cols = columns
    if state["exists"]:
        new_cols, more = _reconcile(sheet, columns, state["columns"])
        notes.extend(more)

    rows, skipped = pi.build_rows(sheet, columns)
    skipped_out = [
        {"row": r, "reason": why} for r, why in skipped[: pi.MAX_SKIP_REASONS]
    ]
    if not rows:
        raise pi.SpreadsheetError(
            f"None of the {len(sheet.rows)} rows could be imported, so nothing was changed. "
            "Check the column types in the preview, a column marked number or date must hold only numbers or dates.",
            422,
            "SPREADSHEET_NO_ROWS",
            {"skipped": skipped_out, "rows_skipped": len(skipped)},
        )

    try:
        replaced = 0
        if not state["exists"]:
            await pi.create_table(db, table, columns, user.tenant_id)
        elif new_cols:
            await pi.add_columns(db, table, new_cols)
        if plan.mode == "replace" or (plan.mode == "create" and state["exists"]):
            replaced = await pi.delete_owner_rows(db, table, user.id)
        imported = await pi.insert_rows(db, table, columns, rows, user.id)

        if existing is None:
            schema_json = pi.build_schema_json(
                domain=domain,
                label=label,
                description=(plan.description or "").strip() or None,
                record_noun=plan.record_noun.strip(),
                record_noun_plural=plan.record_noun_plural.strip(),
                table=table,
                columns=columns,
                title_column=title,
            )
        else:
            schema_json = pi.merge_new_columns(
                copy.deepcopy(existing.schema_json or {}), new_cols
            )
        schema_json, problems = await validate_portfolio_schema(
            db,
            schema_json,
            domain,
            label=existing.label if existing else label,
            record_noun=existing.record_noun if existing else plan.record_noun.strip(),
            record_noun_plural=(
                existing.record_noun_plural
                if existing
                else plan.record_noun_plural.strip()
            ),
        )
        if problems:
            raise pi.SpreadsheetError(
                "The schema made from this file did not pass the checks, so nothing was saved: "
                + "; ".join(problems[:5]),
                422,
                "INVALID_PORTFOLIO_SCHEMA",
                {"problems": problems},
            )
        target = existing
        if target is None:
            target = PortfolioSchema(
                id=uuid.uuid4(),
                tenant_id=user.tenant_id,
                domain_name=domain,
                label=label,
                description=(plan.description or "").strip() or None,
                record_noun=plan.record_noun.strip(),
                record_noun_plural=plan.record_noun_plural.strip(),
                schema_json=schema_json,
                is_active=True,
                created_by=user.id,
            )
            db.add(target)
        else:
            target.schema_json = schema_json
        await db.commit()
        await db.refresh(target)
    except pi.SpreadsheetError:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        logger.exception("portfolio import into %s failed", table)
        raise pi.SpreadsheetError(
            f"The import failed and nothing was saved. The database said: {str(e).splitlines()[0][:300] if str(e) else type(e).__name__}",
            500,
            "SPREADSHEET_IMPORT_FAILED",
        ) from e

    return {
        "schema": _serialize(target, None),
        "table": table,
        "mode": plan.mode,
        "rows_imported": imported,
        "rows_replaced": replaced,
        "rows_skipped": len(skipped),
        "skipped": skipped_out,
        "notes": notes + sheet.warnings,
        "title_column": title,
        "columns": [
            {"name": c["name"], "label": c["label"], "type": c["type"]} for c in columns
        ],
    }


@router.get("/import/capabilities")
async def import_capabilities(user: User = Depends(get_current_user)) -> JSONResponse:
    """What the spreadsheet import accepts on this server."""
    return success(
        {
            "formats": pi.accepted_formats(),
            "max_rows": pi.MAX_ROWS,
            "max_bytes": pi.MAX_BYTES,
            "max_columns": pi.MAX_COLUMNS,
        }
    )


@router.post("/import/preview")
async def import_preview(
    file: UploadFile = File(...),
    domain_name: str | None = Form(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Read an uploaded sheet and suggest column names and types, nothing is saved."""
    try:
        sheet = await _read_upload(file)
        out = pi.preview(sheet)
        out["filename"] = file.filename
        out["existing_columns"] = None
        if domain_name:
            existing = await _find_schema(db, user.tenant_id, domain_name)
            table = pi.table_name_for(user.tenant_id, domain_name)
            if existing and pi.schema_source_table(existing.schema_json) == table:
                state = await pi.table_state(db, table, user.tenant_id)
                if state["exists"] and state["ours"]:
                    cols = {
                        k: v[0]
                        for k, v in state["columns"].items()
                        if k not in pi.SYSTEM_COLUMNS
                    }
                    out["existing_columns"] = [
                        {"name": k, "type": v} for k, v in cols.items()
                    ]
                    for c in out["columns"]:
                        if c["name"] in cols:
                            c["type"] = cols[c["name"]]
                    main = (existing.schema_json or {}).get("main_table", {})
                    out["suggested_title_column"] = (
                        main.get("title_column") or out["suggested_title_column"]
                    )
        return success(out)
    except pi.SpreadsheetError as e:
        return _sheet_error(e)


@router.post("/import")
async def import_spreadsheet(
    file: UploadFile = File(...),
    plan: str = Form(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Create or refill a pf_ table from the sheet and save the schema that reads it."""
    try:
        parsed = _parse_plan(plan)
        sheet = await _read_upload(file)
        result = await _run_import(db, user, sheet, parsed)
        return success(result, status_code=201 if parsed.mode == "create" else 200)
    except pi.SpreadsheetError as e:
        return _sheet_error(e)


def sample_plan(sheet: pi.Sheet, mode: str) -> ImportPlan:
    pv = pi.preview(sheet)
    return ImportPlan(
        domain_name=SAMPLE_DOMAIN,
        label="Energy trading book",
        description="Sample power and gas trades with hub, direction, volume in MWh and price in EUR/MWh.",
        record_noun="trade",
        record_noun_plural="trades",
        title_column="trade_ref",
        columns=[
            {
                "index": c["index"],
                "source": c["source"],
                "name": c["name"],
                "label": c["label"],
                "type": c["type"],
            }
            for c in pv["columns"]
        ],
        mode=mode,
    )


@router.post("/import/sample")
async def import_sample(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """One click demo, an Energy trading book filled with sample trades owned by the caller."""
    try:
        sheet = pi.read_sheet(pi.SAMPLE_PATH.name, pi.sample_bytes())
        existing = await _find_schema(db, user.tenant_id, SAMPLE_DOMAIN)
        plan = sample_plan(sheet, "replace" if existing else "create")
        result = await _run_import(db, user, sheet, plan)
        result["sample"] = True
        return success(result, status_code=201 if plan.mode == "create" else 200)
    except pi.SpreadsheetError as e:
        return _sheet_error(e)


def _cell(v: Any) -> Any:
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, uuid.UUID):
        return str(v)
    return v


@router.get("/{schema_id}/rows")
async def list_my_rows(
    schema_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> JSONResponse:
    """The caller's own rows in a spreadsheet-made table, newest first."""
    res = await db.execute(
        select(PortfolioSchema).where(
            PortfolioSchema.id == schema_id,
            PortfolioSchema.tenant_id == user.tenant_id,
        )
    )
    schema = res.scalar_one_or_none()
    if not schema:
        return error("Schema not found", 404)
    table = pi.schema_source_table(schema.schema_json)
    if not table or not pi.is_import_table(table, user.tenant_id, schema.domain_name):
        return error(
            "Rows can be shown here only for schemas created from a spreadsheet.",
            400,
            error_code="PORTFOLIO_NOT_IMPORTED",
        )
    state = await pi.table_state(db, table, user.tenant_id)
    if not state["exists"] or not state["ours"]:
        return error(
            f"The table {table} behind this schema is gone. Delete the schema and create it again.",
            404,
            error_code="PORTFOLIO_TABLE_MISSING",
        )
    labels = (schema.schema_json or {}).get("main_table", {}).get("columns", {})
    cols = [c for c in state["columns"] if c not in ("owner_id", "id")]
    rows = (
        await db.execute(
            text(
                f"SELECT {', '.join(cols)} FROM {table} WHERE owner_id = :owner ORDER BY created_at DESC, id LIMIT :limit"
            ),
            {"owner": user.id, "limit": limit},
        )
    ).all()
    total = await pi.count_owner_rows(db, table, user.id)
    return success(
        {
            "table": table,
            "total": total,
            "columns": [
                {
                    "name": c,
                    "label": (labels.get(c) or {}).get("label") or pi.humanize(c),
                }
                for c in cols
            ],
            "rows": [[_cell(v) for v in r] for r in rows],
        }
    )
