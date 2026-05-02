from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from app.core.audit import log_action
from app.core.config import settings
from app.core.deps import get_current_user, get_db
from app.core.notifications import create_notification
from app.core.responses import error, success
from app.core.sanitize import is_safe_url, sanitize_input
from app.core.ws_manager import ws_manager
from app.schemas.agents import (
    CreateAgentRequest,
    ExecuteRequest,
    PublishAgentRequest,
    ReviewAgentRequest,
    UpdateAgentRequest,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "apps" / "agent-runtime"))

from models.agent import Agent, AgentStatus, AgentType
from models.agent_share import AgentShare, SharePermission
from models.agent_revision import AgentRevision
from models.execution import Execution, ExecutionStatus
from models.marketplace import Subscription
from models.mcp_connection import AgentMCPTool, UserMCPConnection
from models.user import User

router = APIRouter(prefix="/api/agents", tags=["agents"])

# Lazy singleton for cache orchestrator
_cache_orchestrator: Any = None


class _StopDrift(Exception):
    """Sentinel used to short-circuit the drift try-block when the toggle is off."""

    pass


async def _persist_drift_alerts(
    db: AsyncSession,
    drift_alerts: list[Any],
    agent: Agent,
    execution_id: str,
) -> None:
    """Turn dataclass DriftAlert instances returned by DriftDetector into DB
    rows so they show up at GET /api/analytics/drift-alerts and in the UI."""
    if not drift_alerts:
        return
    import uuid as _uuid
    from models.drift_alert import DriftAlert as DriftAlertRow

    for a in drift_alerts:
        try:
            db.add(
                DriftAlertRow(
                    tenant_id=agent.tenant_id,
                    agent_id=agent.id,
                    execution_id=_uuid.UUID(execution_id) if execution_id else None,
                    severity=a.severity,
                    metric=a.metric_name,
                    baseline_value=a.baseline_value,
                    current_value=a.current_value,
                    deviation_pct=a.deviation_pct,
                    acknowledged=False,
                )
            )
        except Exception:
            continue
    try:
        await db.commit()
    except Exception:
        await db.rollback()


async def _drift_enabled(agent: Agent | None) -> bool:
    """Three-level toggle (most specific wins):"""
    import os as _os

    if agent is not None:
        cfg = agent.model_config_ or {}
        if cfg.get("drift_detection") is False:
            return False
    # Tenant-level Redis override
    if agent is not None and getattr(agent, "tenant_id", None):
        try:
            import redis.asyncio as aioredis
            from app.core.config import settings

            r = aioredis.from_url(str(settings.redis_url), decode_responses=True)
            raw = await r.get(f"drift:config:enabled:{agent.tenant_id}")
            await r.aclose()
            if raw is not None:
                return raw.strip().lower() not in ("0", "false", "no", "off")
        except Exception:
            pass
    env = (_os.environ.get("DRIFT_DETECTION_ENABLED", "true") or "").strip().lower()
    return env not in ("0", "false", "no", "off")


def _get_cache_orchestrator() -> Any:
    """Lazily initialize the cache orchestrator. Returns None on failure."""
    global _cache_orchestrator
    if _cache_orchestrator is None:
        try:
            from app.core.config import settings
            from engine.cache.orchestrator import CacheOrchestrator

            _cache_orchestrator = CacheOrchestrator(
                redis_url=settings.redis_url,
                enable_exact=True,
                enable_semantic=True,
                enable_prompt=True,
            )
        except Exception:
            import logging

            logging.getLogger(__name__).warning(
                "Failed to initialize CacheOrchestrator, running without cache"
            )
    return _cache_orchestrator


def _build_effective_system_prompt(
    base_prompt: str,
    tool_config: dict[str, Any] | None,
) -> str:
    """Append per-tool usage guidelines to the system prompt when tool_config is set."""
    if not tool_config:
        return base_prompt

    lines: list[str] = []
    for tool_name, tc in tool_config.items():
        parts: list[str] = []
        instructions = tc.get("usage_instructions", "").strip()
        if instructions:
            parts.append(instructions)
        max_calls = tc.get("max_calls", 0)
        if max_calls and max_calls > 0:
            parts.append(f"Maximum {max_calls} calls per execution.")
        if tc.get("require_approval"):
            parts.append(
                "Requires human approval before each call — explain why you need it."
            )
        defaults = tc.get("parameter_defaults", {})
        if defaults:
            defaults_str = ", ".join(f"{k}={v}" for k, v in defaults.items())
            parts.append(f"Default parameters: {defaults_str}")
        if parts:
            lines.append(f"- **{tool_name}**: {' '.join(parts)}")

    if not lines:
        return base_prompt

    section = "\n\n## Tool Usage Guidelines\n" + "\n".join(lines)
    return (base_prompt or "").rstrip() + section


def _slugify(name: str) -> str:
    import re

    slug = name.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[-\s]+", "-", slug)
    return slug[:255]


def _serialize_agent(a: Agent) -> dict[str, Any]:
    # Try to expose creator email/name when the relationship was eager-loaded;
    # fall back to None silently if not (review-queue admin view requests it).
    creator_email = None
    creator_name = None
    try:
        if getattr(a, "creator", None) is not None:
            creator_email = getattr(a.creator, "email", None)
            creator_name = getattr(a.creator, "full_name", None) or getattr(
                a.creator, "name", None
            )
    except Exception:
        pass
    data = {
        "id": str(a.id),
        "name": a.name,
        "slug": a.slug,
        "description": a.description,
        "system_prompt": a.system_prompt,
        "agent_type": a.agent_type.value,
        "status": a.status.value,
        "version": a.version,
        "icon_url": a.icon_url,
        "category": a.category,
        "mode": getattr(a, "mode", None),
        "example_prompts": getattr(a, "example_prompts", None),
        "model_config": a.model_config_,
        "is_published": a.is_published,
        "creator_id": str(a.creator_id),
        "creator_email": creator_email,
        "creator_name": creator_name,
        "tenant_id": str(a.tenant_id),
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "updated_at": a.updated_at.isoformat() if a.updated_at else None,
    }
    # Versioning fields (added by migration e5f6a7b8c9d0)
    if hasattr(a, "version_tag"):
        data["version_tag"] = a.version_tag
    if hasattr(a, "traffic_weight"):
        data["traffic_weight"] = float(a.traffic_weight) if a.traffic_weight else None
    if hasattr(a, "parent_agent_id"):
        data["parent_agent_id"] = str(a.parent_agent_id) if a.parent_agent_id else None
    if hasattr(a, "per_execution_cost_limit"):
        data["per_execution_cost_limit"] = (
            float(a.per_execution_cost_limit) if a.per_execution_cost_limit else None
        )
    if hasattr(a, "daily_cost_limit"):
        data["daily_cost_limit"] = (
            float(a.daily_cost_limit) if a.daily_cost_limit else None
        )
    return data


def _serialize_agent_summary(a: Agent) -> dict[str, Any]:
    return {
        "id": str(a.id),
        "name": a.name,
        "slug": a.slug,
        "description": a.description,
        "agent_type": a.agent_type.value,
        "status": a.status.value,
        "version": a.version,
        "icon_url": a.icon_url,
        "category": a.category,
        "model_config": a.model_config_,
    }


@router.delete("/bulk")
async def bulk_delete_agents(
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Delete multiple agents by ID. Only deletes agents owned by the current tenant."""
    ids = body.get("ids", [])
    if not ids or len(ids) > 100:
        return error("Provide 1-100 agent IDs", 400)

    try:
        agent_uuids = [uuid.UUID(str(i)) for i in ids]
    except (ValueError, AttributeError):
        return error("Invalid agent ID format", 400)

    result = await db.execute(
        delete(Agent).where(
            Agent.id.in_(agent_uuids),
            Agent.tenant_id == user.tenant_id,
        )
    )
    await db.commit()
    return success({"deleted": result.rowcount, "requested": len(ids)})


@router.get("")
async def list_agents(
    search: str = Query(
        "", max_length=255, description="Search by name or description"
    ),
    category: str = Query("", description="Filter by category"),
    status: str = Query("", description="Filter by status: active, draft, archived"),
    mode: str = Query("", description="Filter by mode: agent, pipeline"),
    sort: str = Query("newest", description="Sort: newest, oldest, name"),
    scope: str = Query("all", description="Visibility scope: all|mine|shared|tenant"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """List agents visible to the caller."""
    from app.core.permissions import (
        accessible_resource_ids,
        is_admin,
    )

    if scope == "tenant" and not is_admin(user):
        return error("scope=tenant requires admin role", 403)
    accessible_agent_ids = await accessible_resource_ids(
        db,
        user,
        kind="agent",
    )
    # Build the visibility predicate:
    # OOB agents + (admin sees tenant-wide) + (member sees own + shared)
    if scope == "prebuilt":
        # Only pre-built (OOB) agents — used by the "Pre-Built" UI tab
        visibility = Agent.agent_type == AgentType.OOB
    elif is_admin(user) and scope in ("all", "tenant"):
        visibility = or_(
            Agent.tenant_id == user.tenant_id,
            Agent.agent_type == AgentType.OOB,
        )
    elif scope == "mine":
        visibility = and_(
            Agent.tenant_id == user.tenant_id,
            Agent.creator_id == user.id,
        )
    elif scope == "shared":
        ids = list(accessible_agent_ids) or [uuid.UUID(int=0)]
        visibility = or_(
            and_(Agent.tenant_id == user.tenant_id, Agent.id.in_(ids)),
            Agent.agent_type == AgentType.OOB,
        )
    else:
        # default for non-admin: own + shared + OOB
        ids = list(accessible_agent_ids)
        if ids:
            visibility = or_(
                and_(
                    Agent.tenant_id == user.tenant_id,
                    or_(Agent.creator_id == user.id, Agent.id.in_(ids)),
                ),
                Agent.agent_type == AgentType.OOB,
            )
        else:
            visibility = or_(
                and_(Agent.tenant_id == user.tenant_id, Agent.creator_id == user.id),
                Agent.agent_type == AgentType.OOB,
            )
    query = select(Agent).where(
        visibility,
        Agent.status != AgentStatus.ARCHIVED,
    )

    if search:
        # Match name, description, OR slug (SDK clients that resolve
        # agent IDs by slug rely on the slug match — the Java SDK does
        # a single /api/agents?search=<slug> call rather than paginating
        # the full catalog).
        query = query.where(
            or_(
                Agent.name.ilike(f"%{search}%"),
                Agent.description.ilike(f"%{search}%"),
                Agent.slug.ilike(f"%{search}%"),
            )
        )
    if category:
        query = query.where(Agent.category == category)
    if status:
        query = query.where(Agent.status == status)
    if mode:
        # mode is stored in model_config JSONB — skip for now
        pass

    # Sort
    if sort == "oldest":
        query = query.order_by(Agent.created_at.asc())
    elif sort == "name":
        query = query.order_by(Agent.name.asc())
    else:  # newest (default)
        query = query.order_by(Agent.created_at.desc())

    # Count total before pagination
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query) or 0

    # Apply pagination
    query = query.limit(limit).offset(offset)

    result = await db.execute(query)
    agents = result.scalars().all()
    data = [_serialize_agent_summary(a) for a in agents]
    return success(data, meta={"total": total, "limit": limit, "offset": offset})


@router.get("/{agent_id}/export")
async def export_agent(
    agent_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Export agent as JSON template for sharing/importing."""
    result = await db.execute(
        select(Agent).where(
            Agent.id == agent_id,
            or_(Agent.tenant_id == user.tenant_id, Agent.agent_type == AgentType.OOB),
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        return error("Agent not found", 404)
    return success(
        {
            "format": "abenix-template-v1",
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "agent": {
                "name": agent.name,
                "description": agent.description,
                "system_prompt": agent.system_prompt,
                "model_config": agent.model_config_,
                "category": agent.category,
                "icon_url": agent.icon_url,
            },
        }
    )


@router.post("/import")
async def import_agent(
    body: dict[str, Any],
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Import agent from exported JSON template."""
    template = body.get("agent") or body
    name = template.get("name", f"Imported Agent {uuid.uuid4().hex[:6]}")
    agent = Agent(
        tenant_id=user.tenant_id,
        creator_id=user.id,
        name=name,
        slug=_slugify(name) + "-" + uuid.uuid4().hex[:6],
        description=template.get("description", ""),
        system_prompt=template.get("system_prompt", ""),
        model_config_=template.get(
            "model_config",
            {"model": "claude-sonnet-4-5-20250929", "temperature": 0.7, "tools": []},
        ),
        agent_type=AgentType.CUSTOM,
        status=AgentStatus.DRAFT,
        category=template.get("category"),
        icon_url=template.get("icon_url"),
    )
    db.add(agent)
    await db.commit()
    await db.refresh(agent)
    await log_action(
        db,
        user.tenant_id,
        user.id,
        "agent.imported",
        {"agent_id": str(agent.id), "name": name},
        request,
        resource_type="agent",
        resource_id=str(agent.id),
    )
    await db.commit()
    return success(_serialize_agent(agent), status_code=201)


@router.get("/{agent_id}")
async def get_agent(
    agent_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    result = await db.execute(
        select(Agent).where(
            Agent.id == agent_id,
            or_(
                Agent.tenant_id == user.tenant_id,
                Agent.agent_type == AgentType.OOB,
            ),
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        return error("Agent not found", 404)
    # Soft-delete: a deleted agent has status=ARCHIVED. Hide it from regular
    # GETs so the user-visible behaviour matches "I deleted it, it's gone."
    # Admins can still recover by querying /api/agents?status=archived.
    if agent.status == AgentStatus.ARCHIVED and agent.agent_type != AgentType.OOB:
        return error("Agent not found", 404)

    return success(_serialize_agent(agent))


def _self_check_agent(agent: Agent) -> dict[str, Any]:
    """Run a battery of structural checks on an agent's stored config.

    Returns a structured report of {check_name: {status, detail}}. Born
    from the ClaimsIQ Phase A4 incident — the goal is to make every
    silent-coerce bug surface as a deterministic check failure here
    BEFORE the agent ever takes traffic.
    """
    report: dict[str, Any] = {
        "slug": agent.slug,
        "agent_type": str(agent.agent_type),
        "status": str(agent.status),
        "checks": {},
        "ok": True,
    }

    def add(name: str, ok: bool, detail: str = "") -> None:
        report["checks"][name] = {"ok": ok, "detail": detail}
        if not ok:
            report["ok"] = False

    cfg = agent.model_config_ or {}

    # 1. ClaimsIQ-class bug: pipeline_config must NEVER live under
    #    model_config. seed_agents.py reads it from top-level only.
    leaked = []
    for forbidden in ("pipeline_config", "agent_type", "system_prompt", "slug"):
        if forbidden in cfg and forbidden != "pipeline_config":
            leaked.append(forbidden)
    add(
        "no_top_level_keys_leaked_into_model_config",
        not leaked,
        f"leaked: {leaked}" if leaked else "",
    )

    # 2. Pipeline-mode invariants.
    mode = cfg.get("mode")
    is_pipeline = mode == "pipeline"
    if is_pipeline:
        pc = cfg.get("pipeline_config") or {}
        nodes = pc.get("nodes") if isinstance(pc, dict) else None
        add(
            "pipeline_has_nodes",
            bool(nodes),
            (
                "mode=pipeline but pipeline_config.nodes is missing or empty "
                "— check the seed YAML"
                if not nodes
                else f"{len(nodes)} nodes"
            ),
        )
        # Each node needs id + (type or tool_name).
        bad_nodes = []
        for n in nodes or []:
            if not isinstance(n, dict):
                bad_nodes.append(repr(n))
                continue
            if not n.get("id"):
                bad_nodes.append("(no id)")
                continue
            if not n.get("type") and not n.get("tool_name"):
                bad_nodes.append(n.get("id"))
        add(
            "pipeline_nodes_well_formed",
            not bad_nodes,
            f"malformed: {bad_nodes}" if bad_nodes else "",
        )
    else:
        add(
            "pipeline_mode_consistent",
            "pipeline_config" not in cfg or not cfg.get("pipeline_config"),
            (
                "agent has pipeline_config but mode!=pipeline — "
                "pipeline_config will be ignored at runtime"
                if cfg.get("pipeline_config")
                else ""
            ),
        )

    # 3. Model is set (executor will fall back to a default but a missing
    #    one usually means the YAML lost its model declaration).
    add("model_declared", bool(cfg.get("model")), "")

    # 4. Tools listed in the YAML must exist in the runtime registry.
    tools = cfg.get("tools") or []
    unknown_tools: list[str] = []
    if tools:
        try:
            sys.path.insert(
                0,
                str(Path(__file__).resolve().parents[4] / "apps" / "agent-runtime"),
            )
            from engine.agent_executor import (  # type: ignore
                _ensure_tool_classes,
                _TOOL_CLASSES,
                _CONTEXT_TOOL_FACTORIES,
            )

            _ensure_tool_classes()
            known = set(_TOOL_CLASSES.keys()) | set(_CONTEXT_TOOL_FACTORIES.keys())
            unknown_tools = [t for t in tools if t not in known]
        except Exception as e:
            add(
                "tools_registry_loadable",
                False,
                f"could not load tool registry: {e}",
            )
        else:
            add(
                "tools_registry_loadable",
                True,
                f"{len(known)} tools registered",
            )
    add(
        "tools_all_known",
        not unknown_tools,
        f"unknown: {unknown_tools}" if unknown_tools else "",
    )

    return report


@router.get("/{agent_id}/self-check")
async def self_check_agent(
    agent_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Validate an agent's stored config and report structural issues.

    Accepts either a UUID or a slug so platform engineers can hit
    `GET /api/agents/claimsiq-adjudicate/self-check` without first
    looking up the UUID.
    """
    # Try UUID, fall back to slug.
    agent: Agent | None = None
    try:
        uid = uuid.UUID(agent_id)
        result = await db.execute(
            select(Agent).where(
                Agent.id == uid,
                or_(
                    Agent.tenant_id == user.tenant_id,
                    Agent.agent_type == AgentType.OOB,
                ),
            )
        )
        agent = result.scalar_one_or_none()
    except (ValueError, TypeError):
        pass
    if agent is None:
        result = await db.execute(
            select(Agent).where(
                Agent.slug == agent_id,
                or_(
                    Agent.tenant_id == user.tenant_id,
                    Agent.agent_type == AgentType.OOB,
                ),
            )
        )
        agent = result.scalar_one_or_none()
    if agent is None:
        return error("Agent not found", 404)

    return success(_self_check_agent(agent))


@router.post("")
async def create_agent(
    body: CreateAgentRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    slug = _slugify(body.name)

    existing = await db.execute(
        select(Agent).where(Agent.slug == slug, Agent.tenant_id == user.tenant_id)
    )
    if existing.scalar_one_or_none():
        slug = f"{slug}-{uuid.uuid4().hex[:6]}"

    if body.icon_url and not is_safe_url(body.icon_url):
        return error("Invalid icon URL", 400)

    agent = Agent(
        tenant_id=user.tenant_id,
        creator_id=user.id,
        name=sanitize_input(body.name),
        slug=slug,
        description=sanitize_input(body.description),
        system_prompt=body.system_prompt,
        model_config_=body.agent_model_config.model_dump(),
        agent_type=AgentType.CUSTOM,
        status=AgentStatus.DRAFT,
        category=sanitize_input(body.category) if body.category else body.category,
        icon_url=body.icon_url,
    )
    db.add(agent)
    await db.commit()
    await db.refresh(agent)

    await log_action(
        db,
        user.tenant_id,
        user.id,
        "agent.created",
        {"agent_id": str(agent.id), "name": agent.name},
        request,
        resource_type="agent",
        resource_id=str(agent.id),
    )
    await db.commit()

    return success(_serialize_agent(agent), status_code=201)


@router.put("/{agent_id}")
async def update_agent(
    agent_id: uuid.UUID,
    body: UpdateAgentRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    result = await db.execute(
        select(Agent).where(
            Agent.id == agent_id,
            Agent.tenant_id == user.tenant_id,
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        return error("Agent not found", 404)

    if agent.agent_type == AgentType.OOB:
        return error("Cannot edit pre-built agents", 403)

    # Only creator, admin, or users with edit share can modify
    if agent.creator_id != user.id and user.role.value != "admin":
        share_check = await db.execute(
            select(AgentShare).where(
                AgentShare.agent_id == agent_id,
                AgentShare.shared_with_user_id == user.id,
                AgentShare.permission == SharePermission.EDIT,
            )
        )
        if not share_check.scalar_one_or_none():
            return error(
                "Only the agent creator, admin, or users with edit permission can modify this agent",
                403,
            )

    if body.icon_url is not None and not is_safe_url(body.icon_url):
        return error("Invalid icon URL", 400)

    # Create revision snapshot BEFORE applying changes
    try:
        prev_state = {
            "name": agent.name,
            "description": agent.description,
            "system_prompt": agent.system_prompt,
            "model_config": agent.model_config_,
            "category": agent.category,
            "status": agent.status.value,
        }
        # Get next revision number
        rev_count = await db.execute(
            select(AgentRevision).where(AgentRevision.agent_id == agent_id)
        )
        rev_num = len(rev_count.scalars().all()) + 1

        changes = []
        if body.name is not None and body.name != agent.name:
            changes.append(f"name: '{agent.name}' → '{body.name}'")
        if body.system_prompt is not None and body.system_prompt != agent.system_prompt:
            changes.append("system prompt updated")
        if body.agent_model_config is not None:
            changes.append("model config updated")
        if body.category is not None and body.category != agent.category:
            changes.append(f"category: {agent.category} → {body.category}")
    except Exception:
        rev_num = 1
        prev_state = {}
        changes = ["update"]

    if body.name is not None:
        agent.name = sanitize_input(body.name)
        agent.slug = _slugify(body.name)
    if body.description is not None:
        agent.description = sanitize_input(body.description)
    if body.system_prompt is not None:
        agent.system_prompt = body.system_prompt
    if body.agent_model_config is not None:
        agent.model_config_ = body.agent_model_config.model_dump()
    if body.category is not None:
        agent.category = sanitize_input(body.category)
    if body.icon_url is not None:
        agent.icon_url = body.icon_url
    if body.version is not None:
        agent.version = body.version
    if body.status is not None:
        try:
            agent.status = AgentStatus(body.status)
        except ValueError:
            return error(f"Invalid status: {body.status}", 400)

    await db.commit()
    await db.refresh(agent)

    # Save revision after changes
    try:
        new_state = {
            "name": agent.name,
            "description": agent.description,
            "system_prompt": agent.system_prompt,
            "model_config": agent.model_config_,
            "category": agent.category,
            "status": agent.status.value,
        }
        revision = AgentRevision(
            id=uuid.uuid4(),
            agent_id=agent_id,
            revision_number=rev_num,
            changed_by=user.id,
            change_type="config_update",
            previous_state=prev_state,
            new_state=new_state,
            diff_summary="; ".join(changes) if changes else "Updated",
        )
        db.add(revision)

        # Notify collaborators (shared users with edit permission)
        share_result = await db.execute(
            select(AgentShare.shared_with_user_id).where(
                AgentShare.agent_id == agent_id,
                AgentShare.shared_with_user_id.isnot(None),
                AgentShare.shared_with_user_id != user.id,
            )
        )
        collab_ids = [row[0] for row in share_result.all()]
        for collab_id in collab_ids:
            try:
                await create_notification(
                    db,
                    tenant_id=user.tenant_id,
                    user_id=collab_id,
                    type="agent_modified",
                    title=f"Agent updated: {agent.name}",
                    message=f"{user.full_name} modified '{agent.name}': {'; '.join(changes[:3])}",
                    link=f"/agents/{agent_id}/chat",
                )
            except Exception:
                pass
        await db.commit()
    except Exception:
        pass  # Revision tracking failure should not block agent update

    return success(_serialize_agent(agent))


@router.get("/{agent_id}/revisions")
async def list_revisions(
    agent_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """List change history for an agent."""
    result = await db.execute(
        select(AgentRevision)
        .where(AgentRevision.agent_id == agent_id)
        .order_by(AgentRevision.revision_number.desc())
        .limit(50)
    )
    revisions = result.scalars().all()
    return success(
        [
            {
                "id": str(r.id),
                "revision_number": r.revision_number,
                "changed_by": str(r.changed_by),
                "change_type": r.change_type,
                "diff_summary": r.diff_summary,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in revisions
        ]
    )


@router.post("/{agent_id}/revisions/{revision_id}/revert")
async def revert_to_revision(
    agent_id: uuid.UUID,
    revision_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Revert agent to a previous revision."""
    rev_result = await db.execute(
        select(AgentRevision).where(
            AgentRevision.id == revision_id, AgentRevision.agent_id == agent_id
        )
    )
    revision = rev_result.scalar_one_or_none()
    if not revision or not revision.previous_state:
        return error("Revision not found", 404)

    agent_result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = agent_result.scalar_one_or_none()
    if not agent:
        return error("Agent not found", 404)

    # Apply previous state
    prev = revision.previous_state
    if prev.get("name"):
        agent.name = prev["name"]
    if prev.get("description") is not None:
        agent.description = prev["description"]
    if prev.get("system_prompt") is not None:
        agent.system_prompt = prev["system_prompt"]
    if prev.get("model_config") is not None:
        agent.model_config_ = prev["model_config"]
    if prev.get("category"):
        agent.category = prev["category"]

    # Create a revert revision
    rev_count = await db.execute(
        select(AgentRevision).where(AgentRevision.agent_id == agent_id)
    )
    new_rev = AgentRevision(
        id=uuid.uuid4(),
        agent_id=agent_id,
        revision_number=len(rev_count.scalars().all()) + 1,
        changed_by=user.id,
        change_type="revert",
        previous_state=revision.new_state,  # Current state before revert
        new_state=revision.previous_state,  # State we're reverting to
        diff_summary=f"Reverted to revision #{revision.revision_number}",
    )
    db.add(new_rev)
    await db.commit()

    return success({"reverted": True, "to_revision": revision.revision_number})


@router.delete("/{agent_id}")
async def delete_agent(
    agent_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    result = await db.execute(
        select(Agent).where(
            Agent.id == agent_id,
            Agent.tenant_id == user.tenant_id,
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        return error("Agent not found", 404)

    # Only creator or admin can delete
    if agent.creator_id != user.id and user.role.value != "admin":
        return error("Only the agent creator or an admin can delete this agent", 403)

    if agent.agent_type == AgentType.OOB:
        return error("Cannot delete pre-built agents", 403)

    agent.status = AgentStatus.ARCHIVED
    await db.commit()

    return success({"id": str(agent.id), "status": "archived"})


@router.post("/{agent_id}/duplicate")
async def duplicate_agent(
    agent_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    result = await db.execute(
        select(Agent).where(
            Agent.id == agent_id,
            or_(
                Agent.tenant_id == user.tenant_id,
                Agent.agent_type == AgentType.OOB,
            ),
        )
    )
    source = result.scalar_one_or_none()
    if not source:
        return error("Agent not found", 404)

    new_slug = f"{source.slug}-copy-{uuid.uuid4().hex[:6]}"

    clone = Agent(
        tenant_id=user.tenant_id,
        creator_id=user.id,
        name=f"{source.name} (Copy)",
        slug=new_slug,
        description=source.description,
        system_prompt=source.system_prompt,
        model_config_=dict(source.model_config_) if source.model_config_ else {},
        agent_type=AgentType.CUSTOM,
        status=AgentStatus.DRAFT,
        category=source.category,
        icon_url=source.icon_url,
    )
    db.add(clone)
    await db.commit()
    await db.refresh(clone)

    return success(_serialize_agent(clone), status_code=201)


@router.post("/{agent_id}/publish")
async def publish_agent(
    agent_id: uuid.UUID,
    body: PublishAgentRequest | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    result = await db.execute(
        select(Agent).where(
            Agent.id == agent_id,
            Agent.tenant_id == user.tenant_id,
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        return error("Agent not found", 404)

    if agent.agent_type == AgentType.OOB:
        return error("Cannot publish pre-built agents", 403)

    if not agent.name or not agent.system_prompt:
        return error("Agent must have a name and system prompt to publish", 400)

    visibility = "tenant"
    if body:
        if body.marketplace_price is not None:
            agent.marketplace_price = body.marketplace_price
        if body.category is not None:
            agent.category = body.category
        if body.visibility:
            visibility = body.visibility

    if visibility == "public":
        # Marketplace publish — requires admin review
        agent.status = AgentStatus.PENDING_REVIEW
        agent.is_published = False
        await db.commit()
        await db.refresh(agent)
        await log_action(
            db,
            user.tenant_id,
            user.id,
            "agent.submitted_for_review",
            {"agent_id": str(agent.id), "name": agent.name},
        )
        await db.commit()
    else:
        # Tenant or specific-user publish — activate immediately (no marketplace review needed)
        agent.status = AgentStatus.ACTIVE
        agent.is_published = visibility != "tenant"  # True for specific-user sharing
        await db.commit()
        await db.refresh(agent)
        await log_action(
            db,
            user.tenant_id,
            user.id,
            "agent.published",
            {"agent_id": str(agent.id), "name": agent.name, "visibility": visibility},
        )
        await db.commit()

    return success(_serialize_agent(agent))


@router.post("/{agent_id}/review")
async def review_agent(
    agent_id: uuid.UUID,
    body: ReviewAgentRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if user.role.value not in ("admin",):
        return error("Admin access required", 403)

    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        return error("Agent not found", 404)

    if agent.status != AgentStatus.PENDING_REVIEW:
        return error("Agent is not pending review", 400)

    if body.action == "approve":
        agent.status = AgentStatus.ACTIVE
        agent.is_published = True
        agent.rejection_reason = None
    else:
        agent.status = AgentStatus.REJECTED
        agent.is_published = False
        agent.rejection_reason = body.reason

    await db.commit()
    await db.refresh(agent)

    await log_action(
        db,
        agent.tenant_id,
        user.id,
        "agent.reviewed",
        {"agent_id": str(agent.id), "action": body.action},
    )
    await db.commit()

    return success(_serialize_agent(agent))


@router.post("/{agent_id}/validate-smart")
async def validate_agent_smart(
    agent_id: uuid.UUID,
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Run the layered AI Validate stack on a saved agent."""
    from engine.pipeline_validator import validate_pipeline
    from engine.pipeline_validator_semantic import validate_semantic
    from engine.pipeline_validator_llm import critique

    result = await db.execute(
        select(Agent).where(
            Agent.id == agent_id,
            or_(Agent.tenant_id == user.tenant_id, Agent.agent_type == AgentType.OOB),
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        return error("Agent not found", 404)

    deep = bool(body.get("deep", False))
    cfg = agent.model_config_ or {}
    tool_names = cfg.get("tools", []) or []

    # Agent-level structural checks — these mirror what the AI builder generates.
    agent_errors: list[dict] = []
    agent_warnings: list[dict] = []
    if not (agent.system_prompt or "").strip():
        agent_errors.append(
            {
                "node_id": "",
                "field": "system_prompt",
                "severity": "error",
                "message": "Agent has no system prompt",
                "suggestion": "Add a system_prompt describing the agent's role and behavior.",
            }
        )
    if not tool_names:
        agent_warnings.append(
            {
                "node_id": "",
                "field": "model_config.tools",
                "severity": "warning",
                "message": "Agent has no tools configured",
                "suggestion": "Add at least one tool, or confirm this agent only needs the LLM.",
            }
        )
    max_iter = cfg.get("max_iterations", 10)
    if isinstance(max_iter, int) and max_iter > 40:
        agent_warnings.append(
            {
                "node_id": "",
                "field": "model_config.max_iterations",
                "severity": "warning",
                "message": f"max_iterations={max_iter} is high — will run slowly and cost a lot",
                "suggestion": "Consider keeping max_iterations at or below 30 unless there's a clear reason.",
            }
        )

    # Pipeline-mode — run Tier 1/2 against the DAG.
    pipeline_cfg = cfg.get("pipeline_config") or {}
    nodes = pipeline_cfg.get("nodes") or []

    # Agent-declared input variables are available as flat context keys at
    # runtime (e.g. {{model_name}}), so the validator should treat them as
    # valid template targets.
    input_var_names = {
        v.get("name")
        for v in (cfg.get("input_variables") or [])
        if isinstance(v, dict) and v.get("name")
    }

    tier1_dict: dict | None = None
    tier2_dict: dict | None = None
    if nodes:
        try:
            from engine.agent_executor import build_tool_registry

            tool_registry = build_tool_registry(tool_names)
            t1 = validate_pipeline(
                nodes, tool_registry, available_context_keys=input_var_names
            )
            tier1_dict = t1.to_dict()
            t2 = validate_semantic(nodes, tool_registry, tier1=t1)
            tier2_dict = t2.to_dict()
        except Exception as e:
            agent_warnings.append(
                {
                    "node_id": "",
                    "field": "pipeline_config",
                    "severity": "warning",
                    "message": f"Could not run pipeline validator: {e}",
                    "suggestion": "",
                }
            )

    tier3_dict: dict | None = None
    if deep:
        config_snapshot: dict[str, Any] = {
            "name": agent.name,
            "description": agent.description,
            "system_prompt": agent.system_prompt,
            "tools": tool_names,
            "model_config": cfg,
        }
        if nodes:
            config_snapshot["pipeline_config"] = {"nodes": nodes}
        report = await critique(
            kind="pipeline" if nodes else "agent",
            config=config_snapshot,
            purpose=agent.description or "",
        )
        tier3_dict = report.to_dict()

    has_errors = (
        bool(agent_errors)
        or (tier1_dict and not tier1_dict.get("valid", True))
        or (tier2_dict and tier2_dict.get("errors"))
    )
    valid = not has_errors
    severity = (
        "error"
        if has_errors
        else (
            "warn"
            if agent_warnings or (tier2_dict and tier2_dict.get("warnings"))
            else "ok"
        )
    )
    score = (
        (tier3_dict or {}).get("coherence_score")
        if tier3_dict
        else (10 if severity == "ok" else 6 if severity == "warn" else 2)
    )

    return success(
        {
            "agent": {"errors": agent_errors, "warnings": agent_warnings},
            "tier1": tier1_dict,
            "tier2": tier2_dict,
            "tier3": tier3_dict,
            "overall": {"valid": valid, "severity": severity, "score": score},
        }
    )


@router.post("/{agent_id}/execute", response_model=None)
async def execute_agent(
    agent_id: uuid.UUID,
    body: ExecuteRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse | JSONResponse:
    from app.core.usage import check_limit, check_user_quota

    # Tri-state wait resolution (belt-and-suspenders for the SDK fix).
    # If the client did not specify wait, default based on caller type:
    #   - X-API-Key (SDK) → wait=True  (synchronous; SDK has no live stream)
    #   - JWT/cookie (browser) → wait=False (async; UI streams progress)
    # An explicit True/False from the client always wins. This means even
    # if a future SDK ships with `wait` accidentally dropped from the
    # request body, the server still returns synchronously to API-key
    # callers, so standalone apps never see an empty-output regression.
    if body.wait is None:
        is_api_key_caller = getattr(user, "_api_key_scopes", None) is not None
        body.wait = bool(is_api_key_caller)
        # Also flip stream off for API-key callers when we're defaulting
        # to wait=True — streaming + wait are incompatible (stream short-
        # circuits before the wait branch). Browser callers keep stream
        # default (True) since they want SSE.
        if is_api_key_caller and body.stream is True:
            body.stream = False

    allowed, limit_msg = await check_limit(db, user.tenant_id, user.id)
    if not allowed:
        return error(limit_msg, 429)

    # Check per-user quota
    quota_error = await check_user_quota(user)
    if quota_error:
        return error(quota_error, 429)

    result = await db.execute(
        select(Agent).where(
            Agent.id == agent_id,
            or_(
                Agent.tenant_id == user.tenant_id,
                Agent.agent_type == AgentType.OOB,
                # Subscribers can execute published agents from other tenants
                Agent.id.in_(
                    select(Subscription.agent_id).where(
                        Subscription.user_id == user.id,
                        Subscription.status == "active",
                    )
                ),
                # Shared agents with execute or edit permission
                Agent.id.in_(
                    select(AgentShare.agent_id).where(
                        AgentShare.shared_with_user_id == user.id,
                        AgentShare.permission.in_(
                            [SharePermission.EXECUTE, SharePermission.EDIT]
                        ),
                    )
                ),
            ),
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        return error("Agent not found", 404)

    if agent.status not in (AgentStatus.ACTIVE, AgentStatus.DRAFT):
        return error("Agent is not in an executable state", 400)

    model_cfg = agent.model_config_ or {}
    is_pipeline = model_cfg.get("mode") == "pipeline"
    model = model_cfg.get("model", "claude-sonnet-4-5-20250929")
    temperature = model_cfg.get("temperature", 0.7)
    tool_names = model_cfg.get("tools", [])
    # Allow agent yamls to override the executor's default iteration cap.
    # Important for tool-heavy agents (hedge advisor, renewal copilot, stress
    # test) where the default cap of 10 is too small.
    agent_max_iterations = model_cfg.get("max_iterations")
    agent_max_tokens = model_cfg.get("max_tokens", 4096)

    agent_cache_enabled = model_cfg.get("cache", True) is not False

    sanitized_message = sanitize_input(body.message)

    # DLP: scan input for PII before execution
    try:
        from engine.dlp import enforce_dlp, DLPPolicy

        dlp_message, dlp_result = enforce_dlp(
            sanitized_message, DLPPolicy(mode="detect")
        )
        if dlp_result.has_pii:
            # In detect mode: log warning but proceed. In mask/block mode: enforce_dlp handles it.
            sanitized_message = dlp_message
    except ValueError as e:
        # DLP block mode raises ValueError
        return error(str(e), 400)
    except Exception:
        pass  # DLP failure should not block execution

    mcp_connections = await _fetch_mcp_connections(db, agent.id)

    execution = Execution(
        tenant_id=user.tenant_id,
        agent_id=agent.id,
        user_id=user.id,
        input_message=sanitized_message,
        status=ExecutionStatus.RUNNING,
        model_used=model if not is_pipeline else "pipeline",
    )
    db.add(execution)
    await db.commit()
    await db.refresh(execution)

    # Extract context (input variables) from request
    user_context = body.context or {}

    agent_pool = getattr(agent, "runtime_pool", None) or "default"
    if settings.scaling_exec_remote and agent_pool != "inline":
        try:
            import sys
            import os as _os

            _runtime_path = _os.path.join(
                _os.path.dirname(__file__), "..", "..", "..", "agent-runtime"
            )
            _runtime_path = _os.path.abspath(_runtime_path)
            if _runtime_path not in sys.path:
                sys.path.insert(0, _runtime_path)
            from engine.queue_backend import get_queue_backend  # type: ignore

            backend = get_queue_backend()
            payload = {
                "execution_id": str(execution.id),
                "agent_id": str(agent.id),
                "tenant_id": str(user.tenant_id),
                "user_id": str(user.id),
                "message": sanitized_message,
                "context": user_context,
                "is_pipeline": is_pipeline,
            }
            task_id = await backend.submit(agent_pool, payload)

            if body.stream:
                # Client wants the stream — subscribe to the execution
                # bus and yield events as the consumer publishes them.
                from app.core.execution_bus import subscribe_events

                async def _remote_stream() -> AsyncIterator[bytes]:
                    async for evt in subscribe_events(str(execution.id)):
                        data = json.dumps(evt, default=str)
                        ev_name = evt.get("event") or "message"
                        yield f"event: {ev_name}\ndata: {data}\n\n".encode()

                return StreamingResponse(
                    _remote_stream(),
                    media_type="text/event-stream",
                    headers={
                        "Cache-Control": "no-cache",
                        "X-Accel-Buffering": "no",
                        "Connection": "keep-alive",
                    },
                )
            if body.wait:
                from app.core.execution_bus import subscribe_events
                import asyncio as _asyncio

                output_text = ""
                summary: dict[str, Any] = {}
                errored: str | None = None

                async def _collect():
                    nonlocal output_text, summary, errored
                    async for evt in subscribe_events(str(execution.id)):
                        ev = evt.get("event")
                        if ev == "done":
                            output_text = str(evt.get("output") or "")
                            summary = evt.get("summary") or {}
                            return
                        if ev == "error":
                            errored = str(evt.get("error") or "execution failed")
                            # Failed pipelines still publish a summary alongside
                            # the error event — capture it so the response
                            # carries node_results / failed_nodes / status.
                            output_text = str(evt.get("output") or "")
                            summary = evt.get("summary") or {}
                            return

                try:
                    await _asyncio.wait_for(
                        _collect(), timeout=body.wait_timeout_seconds
                    )
                except _asyncio.TimeoutError:
                    errored = f"timed out after {body.wait_timeout_seconds}s"

                if errored:
                    # Return 200 with status=failed so callers can drill into
                    # the execution by id. The consumer has already persisted
                    # the failed row + failure_code; a 5xx here would have
                    # made that invisible to clients (and to dashboards).
                    if errored.startswith("timed out"):
                        return error(errored, 504)
                    _failed_summary = summary or {"status": "failed", "error": errored}
                    if isinstance(_failed_summary, dict) and not _failed_summary.get(
                        "status"
                    ):
                        _failed_summary["status"] = "failed"
                    return success(
                        {
                            "execution_id": str(execution.id),
                            "task_id": task_id,
                            "pool": agent_pool,
                            "mode": "sync_via_queue",
                            "status": "failed",
                            "error": errored,
                            "output": output_text,
                            "summary": _failed_summary,
                        }
                    )
                # Surface pipeline status from the consumer's done event so
                # callers see status=completed/failed without a follow-up GET.
                _qstatus = summary.get("status") if isinstance(summary, dict) else None
                return success(
                    {
                        "execution_id": str(execution.id),
                        "task_id": task_id,
                        "pool": agent_pool,
                        "mode": "sync_via_queue",
                        "status": _qstatus or "completed",
                        "output": output_text,
                        "summary": summary,
                    }
                )

            return success(
                {
                    "execution_id": str(execution.id),
                    "task_id": task_id,
                    "pool": agent_pool,
                    "mode": "async",
                }
            )
        except Exception as _enqueue_err:
            # Enqueue failed — don't strand the client. Fall through to
            # the inline path so the request still succeeds (same
            # behaviour as queue_backend's fallback-to-celery design).
            logging.getLogger(__name__).warning(
                "remote-exec enqueue failed, falling back to inline: %s",
                _enqueue_err,
            )

    # Pipeline agents use PipelineExecutor instead of AgentExecutor
    if is_pipeline:
        pipeline_config = model_cfg.get("pipeline_config")
        if not pipeline_config or not pipeline_config.get("nodes"):
            # Clear, actionable error. The most common cause is the
            # ClaimsIQ-class silent-coerce bug: pipeline_config nested
            # under model_config in the seed YAML. The previous text —
            # "Pipeline agent has no pipeline configuration" — sent us
            # hunting for two hours during Phase A4.
            return error(
                f"Agent '{agent.slug}' is registered as mode=pipeline "
                "but pipeline_config is missing or empty. Likely cause: "
                "pipeline_config nested under model_config in the seed "
                "YAML. Run `python scripts/lint-agent-seeds.py` or "
                "GET /api/agents/{slug}/self-check for details.",
                400,
            )

        if body.stream:
            return StreamingResponse(
                _stream_pipeline_execution(
                    execution_id=execution.id,
                    message=sanitized_message,
                    tool_names=tool_names,
                    pipeline_config=pipeline_config,
                    db=db,
                    context=user_context,
                    tenant_id=str(user.tenant_id),
                    agent_id=str(agent.id),
                    agent_name=agent.name,
                ),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                    "Connection": "keep-alive",
                },
            )

        return await _non_stream_pipeline_execution(
            execution=execution,
            message=sanitized_message,
            tool_names=tool_names,
            pipeline_config=pipeline_config,
            db=db,
            context=user_context,
            tenant_id=str(user.tenant_id),
            agent_name=agent.name,
        )

    # Enterprise context for tools and monitoring
    _enterprise_ctx = {
        "tenant_id": str(user.tenant_id),
        "user_id": str(user.id),
        "agent_name": agent.name,
        "per_execution_cost_limit": (
            float(agent.per_execution_cost_limit)
            if hasattr(agent, "per_execution_cost_limit")
            and agent.per_execution_cost_limit
            else None
        ),
        "daily_cost_limit": (
            float(agent.daily_cost_limit)
            if hasattr(agent, "daily_cost_limit") and agent.daily_cost_limit
            else None
        ),
    }

    # Acting subject for RBAC delegation (if API key holder is acting on behalf of an end user)
    acting_subject = getattr(user, "_acting_subject", None)
    if acting_subject:
        _enterprise_ctx["acting_subject"] = acting_subject.to_dict()
        import logging as _log

        _log.getLogger(__name__).info(
            "Agent execution with acting subject: %s", acting_subject.to_dict()
        )

    # Surface the agent's model_config so tools that need its keys
    # (e.g. atlas_*: model_config.atlas_graphs allow-list) can read it.
    _enterprise_ctx["model_config"] = model_cfg or {}

    # Inject per-tool instructions from tool_config into system prompt
    effective_system_prompt = _build_effective_system_prompt(
        agent.system_prompt or "",
        model_cfg.get("tool_config"),
    )

    from app.services.collection_access import resolve_agent_collections

    _subj_dict = acting_subject.to_dict() if acting_subject is not None else None
    _collection_ids = await resolve_agent_collections(
        db,
        agent_id=agent.id,
        tenant_id=user.tenant_id,
        acting_subject=_subj_dict,
    )
    kb_ids = [str(cid) for cid in _collection_ids]

    if body.stream:
        return StreamingResponse(
            _stream_execution(
                execution_id=execution.id,
                agent_id=agent.id,
                message=sanitized_message,
                system_prompt=effective_system_prompt,
                model=model,
                temperature=temperature,
                tool_names=tool_names,
                mcp_connections=mcp_connections,
                db=db,
                enterprise_ctx=_enterprise_ctx,
                user_context=user_context,
                kb_ids=kb_ids,
                max_iterations=agent_max_iterations,
                max_tokens=agent_max_tokens,
                cache_enabled=agent_cache_enabled,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    return await _non_stream_execution(
        execution=execution,
        message=sanitized_message,
        system_prompt=effective_system_prompt,
        model=model,
        temperature=temperature,
        tool_names=tool_names,
        mcp_connections=mcp_connections,
        db=db,
        enterprise_ctx=_enterprise_ctx,
        user_context=user_context,
        kb_ids=kb_ids,
        max_iterations=agent_max_iterations,
        max_tokens=agent_max_tokens,
        cache_enabled=agent_cache_enabled,
        tool_config=model_cfg.get("tool_config") or {},
    )


async def _stream_pipeline_execution(
    execution_id: uuid.UUID,
    message: str,
    tool_names: list[str],
    pipeline_config: dict[str, Any],
    db: AsyncSession,
    context: dict[str, Any] | None = None,
    tenant_id: str = "",
    agent_id: str = "",
    agent_name: str = "",
    timeout_seconds: int = 120,
) -> Any:
    """Stream pipeline execution with node-level progress events."""
    import asyncio as _asyncio
    from app.core.execution_state import publish_state, complete_state, fail_state

    from engine.agent_executor import build_tool_registry
    from engine.pipeline import (
        PipelineExecutor,
        parse_pipeline_nodes,
        serialize_pipeline_result,
    )

    tool_registry = build_tool_registry(tool_names)

    event_queue: _asyncio.Queue[str | None] = _asyncio.Queue()
    _node_statuses: dict[str, str] = {}
    _completed_nodes = 0

    async def on_node_start(node_id: str, tool_name: str) -> None:
        nonlocal _completed_nodes
        _node_statuses[node_id] = "running"
        data = json.dumps({"node_id": node_id, "tool_name": tool_name})
        await event_queue.put(f"event: node_start\ndata: {data}\n\n")
        await publish_state(
            str(execution_id),
            tenant_id,
            agent_id,
            agent_name,
            "running",
            current_tool=tool_name,
            current_step=f"node: {node_id}",
            node_statuses=_node_statuses,
            iteration=_completed_nodes,
            max_iterations=len(_node_statuses) + 5,
            metadata={"mode": "pipeline"},
        )

    async def on_node_complete(
        node_id: str,
        status: str,
        duration_ms: int,
        output: Any,
        error_message: str | None = None,
        error_type: str | None = None,
    ) -> None:
        nonlocal _completed_nodes
        _node_statuses[node_id] = status
        _completed_nodes += 1

        result_data: dict[str, Any] = {
            "node_id": node_id,
            "status": status,
            "duration_ms": duration_ms,
        }

        # Include error details if failed
        if status == "failed":
            if error_message:
                result_data["error"] = error_message[:2000]
            elif output is not None:
                out_text = str(output) if not isinstance(output, str) else output
                result_data["error"] = out_text[:2000]
            else:
                result_data["error"] = "Unknown error"
            if error_type:
                result_data["error_type"] = error_type

        # Include output preview if successful
        if output is not None and status != "failed":
            out_text = str(output) if not isinstance(output, str) else output
            result_data["output_preview"] = out_text[:500]

        data = json.dumps(result_data, default=str)
        await event_queue.put(f"event: node_complete\ndata: {data}\n\n")
        await publish_state(
            str(execution_id),
            tenant_id,
            agent_id,
            agent_name,
            "running",
            current_step=f"completed: {node_id}",
            node_statuses=_node_statuses,
            iteration=_completed_nodes,
            metadata={"mode": "pipeline"},
        )

    executor = PipelineExecutor(
        tool_registry=tool_registry,
        timeout_seconds=timeout_seconds,
        on_node_start=on_node_start,
        on_node_complete=on_node_complete,
        db_url=str(settings.database_url),
    )

    # Parse pipeline nodes and inject user message as query for search nodes
    raw_nodes = pipeline_config.get("nodes", [])
    pipeline_nodes = parse_pipeline_nodes(raw_nodes)
    for node in pipeline_nodes:
        if node.tool_name == "web_search" and "query" not in node.arguments:
            node.arguments["query"] = message
        _node_statuses[node.id] = "pending"

    # Publish initial state so pipeline shows in live debug immediately
    await publish_state(
        str(execution_id),
        tenant_id,
        agent_id,
        agent_name,
        "running",
        current_step="starting pipeline",
        node_statuses=_node_statuses,
        max_iterations=len(pipeline_nodes),
        metadata={"mode": "pipeline"},
    )

    pipeline_result: list[Any] = [None]

    async def run_pipeline() -> None:
        try:
            result = await executor.execute(
                pipeline_nodes, {"user_message": message, **(context or {})}
            )
            pipeline_result[0] = result

            serialized = serialize_pipeline_result(result)
            serialized["execution_id"] = str(execution_id)

            # Build a text summary from the final output for the chat
            final_text = ""
            if result.final_output:
                if isinstance(result.final_output, str):
                    final_text = result.final_output
                elif isinstance(result.final_output, dict):
                    final_text = result.final_output.get(
                        "response",
                        result.final_output.get("content", str(result.final_output)),
                    )
                else:
                    final_text = str(result.final_output)

            # Emit the final text as a token event so the chat displays it
            if final_text:
                token_data = json.dumps({"text": final_text})
                await event_queue.put(f"event: token\ndata: {token_data}\n\n")

            # Aggregate tokens/cost from node outputs for the done event
            _total_in = 0
            _total_out = 0
            _total_cost = 0.0
            for _nid, nr in (result.node_results or {}).items():
                out = nr.output if hasattr(nr, "output") else None
                if isinstance(out, dict):
                    _total_in += int(out.get("input_tokens", 0) or 0)
                    _total_out += int(out.get("output_tokens", 0) or 0)
                    _total_cost += float(out.get("cost", 0) or 0)
                elif isinstance(out, str):
                    try:
                        p = json.loads(out)
                        if isinstance(p, dict):
                            _total_in += int(p.get("input_tokens", 0) or 0)
                            _total_out += int(p.get("output_tokens", 0) or 0)
                            _total_cost += float(p.get("cost", 0) or 0)
                    except Exception:
                        pass

            done_data = json.dumps(
                {
                    "total_tokens": _total_in + _total_out,
                    "input_tokens": _total_in,
                    "output_tokens": _total_out,
                    "cost": round(_total_cost, 4),
                    "duration_ms": result.total_duration_ms,
                    "model": "pipeline",
                    "pipeline_status": result.status,
                    "execution_path": result.execution_path,
                    "failed_nodes": result.failed_nodes,
                    "node_errors": getattr(result, "node_errors", {}),
                }
            )
            await event_queue.put(f"event: done\ndata: {done_data}\n\n")

        except Exception as e:
            import traceback as _tb

            err_data = json.dumps(
                {
                    "message": str(e),
                    "type": type(e).__name__,
                    "traceback": _tb.format_exc()[:2000],
                }
            )
            await event_queue.put(f"event: error\ndata: {err_data}\n\n")
        finally:
            await event_queue.put(None)

    async def event_generator():
        task = _asyncio.create_task(run_pipeline())
        try:
            while True:
                try:
                    event = await _asyncio.wait_for(event_queue.get(), timeout=15.0)
                except _asyncio.TimeoutError:
                    # SSE heartbeat to keep connection alive during long LLM calls
                    yield ": heartbeat\n\n"
                    continue
                if event is None:
                    break
                yield event
        finally:
            if not task.done():
                task.cancel()

    async for event in event_generator():
        yield event

    # Update execution record
    pr = pipeline_result[0]
    if pr:
        result = await db.execute(select(Execution).where(Execution.id == execution_id))
        execution = result.scalar_one_or_none()
        if execution:
            execution.status = (
                ExecutionStatus.COMPLETED
                if pr.status == "completed"
                else ExecutionStatus.FAILED
            )
            execution.duration_ms = pr.total_duration_ms
            execution.completed_at = datetime.now(timezone.utc)
            if pr.final_output:
                # Apply the same generic post-processor that runs in the
                # NATS consumer path so the inline path produces the same
                # normalized output (no sentiment="mixed", severity="extreme",
                # etc.). See engine/post_process.py for the rationale.
                # Pipeline-level output_schema takes precedence; if absent we
                # fall back to the agent's model_config.output_schema fetched
                # in the same DB query.
                _output_schema_inline = (pipeline_config or {}).get("output_schema")
                if not _output_schema_inline:
                    _agent_row = (
                        (
                            await db.execute(
                                select(Agent).where(Agent.id == uuid.UUID(agent_id))
                            )
                        ).scalar_one_or_none()
                        if agent_id
                        else None
                    )
                    if _agent_row is not None:
                        _output_schema_inline = (_agent_row.model_config_ or {}).get(
                            "output_schema"
                        )
                if _output_schema_inline:
                    try:
                        import sys as _sys
                        from pathlib import Path as _Path

                        _runtime_path = str(
                            _Path(__file__).resolve().parents[4] / "agent-runtime"
                        )
                        if _runtime_path not in _sys.path:
                            _sys.path.insert(0, _runtime_path)
                        from engine.post_process import post_process as _pp  # type: ignore

                        _norm, _w = _pp(pr.final_output, _output_schema_inline)
                        if isinstance(_norm, (dict, list)):
                            pr.final_output = _norm
                    except Exception:
                        pass
                out = pr.final_output
                if isinstance(out, dict):
                    out = out.get("response", out.get("content", str(out)))
                execution.output_message = str(out)[:50000]

            # Aggregate tokens, cost, and tool calls from all pipeline nodes
            serialized_result = serialize_pipeline_result(pr)
            node_results_data = serialized_result.get("node_results", {})
            total_input_tokens = 0
            total_output_tokens = 0
            total_cost = 0.0
            total_tool_calls = 0
            for _nid, nr in (node_results_data or {}).items():
                node_output = nr.get("output") if isinstance(nr, dict) else None
                if isinstance(node_output, dict):
                    total_input_tokens += int(node_output.get("input_tokens", 0) or 0)
                    total_output_tokens += int(node_output.get("output_tokens", 0) or 0)
                    total_cost += float(node_output.get("cost", 0) or 0)
                    total_tool_calls += int(node_output.get("tool_calls_count", 0) or 0)
                elif isinstance(node_output, str):
                    # Try parsing JSON output from agent_step/llm_call
                    try:
                        parsed = json.loads(node_output)
                        if isinstance(parsed, dict):
                            total_input_tokens += int(
                                parsed.get("input_tokens", 0) or 0
                            )
                            total_output_tokens += int(
                                parsed.get("output_tokens", 0) or 0
                            )
                            total_cost += float(parsed.get("cost", 0) or 0)
                            total_tool_calls += int(
                                parsed.get("tool_calls_count", 0) or 0
                            )
                    except (json.JSONDecodeError, TypeError, ValueError):
                        pass

            execution.input_tokens = total_input_tokens or None
            execution.output_tokens = total_output_tokens or None
            execution.cost = round(total_cost, 6) if total_cost > 0 else None
            execution.tool_calls = (
                {"total": total_tool_calls} if total_tool_calls > 0 else None
            )

            # Store pipeline data for flight recorder
            execution.node_results = node_results_data
            execution.execution_trace = {
                "pipeline_status": pr.status,
                "execution_path": pr.execution_path,
                "failed_nodes": pr.failed_nodes,
                "skipped_nodes": getattr(pr, "skipped_nodes", []),
                "node_results": node_results_data,
            }
            await db.commit()
        # Complete live state
        await complete_state(str(execution_id), tenant_id)
    else:
        await fail_state(str(execution_id), tenant_id, "Pipeline returned no result")


async def _non_stream_pipeline_execution(
    execution: Execution,
    message: str,
    tool_names: list[str],
    pipeline_config: dict[str, Any],
    db: AsyncSession,
    context: dict[str, Any] | None = None,
    tenant_id: str = "",
    agent_name: str = "",
) -> JSONResponse:
    """Execute pipeline and return JSON result."""
    from app.core.execution_state import publish_state, complete_state, fail_state

    try:
        from engine.agent_executor import build_tool_registry
        from engine.pipeline import (
            PipelineExecutor,
            parse_pipeline_nodes,
            serialize_pipeline_result,
        )

        # Publish initial running state so it appears in live debug
        await publish_state(
            str(execution.id),
            tenant_id,
            str(execution.agent_id),
            agent_name,
            "running",
            current_step="initializing",
            metadata={"mode": "pipeline"},
        )

        tool_registry = build_tool_registry(tool_names)
        executor = PipelineExecutor(
            tool_registry=tool_registry,
            timeout_seconds=120,
            db_url=os.environ.get("DATABASE_URL", ""),
        )

        raw_nodes = pipeline_config.get("nodes", [])
        pipeline_nodes = parse_pipeline_nodes(raw_nodes)
        for node in pipeline_nodes:
            if node.tool_name == "web_search" and "query" not in node.arguments:
                node.arguments["query"] = message

        # Publish state with node info before execution
        node_names = [n.id for n in pipeline_nodes]
        node_statuses = {n: "pending" for n in node_names}
        await publish_state(
            str(execution.id),
            tenant_id,
            str(execution.agent_id),
            agent_name,
            "running",
            current_step="executing pipeline",
            node_statuses=node_statuses,
            max_iterations=len(pipeline_nodes),
            metadata={"mode": "pipeline"},
        )

        # Provide the user message under multiple common variable names that
        # seed pipelines may reference (ticket_content, prompt, input, etc.)
        # so pipeline templates resolve consistently regardless of wording.
        base_context = {
            "user_message": message,
            "message": message,
            "input": message,
            "prompt": message,
            "content": message,
            "text": message,
            "ticket_content": message,
            "query": message,
            "request": message,
        }
        result = await executor.execute(
            pipeline_nodes, {**base_context, **(context or {})}
        )
    except Exception as e:
        execution.status = ExecutionStatus.FAILED
        execution.error_message = str(e)[:2000]
        from app.core.failure_codes import classify_exception, emit_outcome_metric

        execution.failure_code = classify_exception(e)
        execution.completed_at = datetime.now(timezone.utc)
        emit_outcome_metric(outcome="FAILED", failure_code=execution.failure_code)
        await db.commit()
        await fail_state(str(execution.id), tenant_id, str(e))
        # Return 200 with a failed-result envelope so callers can drill into
        # the execution by id. Returning 500 swallowed execution_id and made
        # the failed run invisible to clients (and to the dashboard).
        return success(
            {
                "execution_id": str(execution.id),
                "status": "failed",
                "failure_code": execution.failure_code,
                "error": str(e)[:2000],
                "node_results": {},
                "execution_path": [],
                "failed_nodes": [],
                "skipped_nodes": [],
                "total_duration_ms": 0,
                "duration_ms": 0,
                "final_output": None,
                "output": None,
                "cost": 0.0,
            }
        )

    serialized = serialize_pipeline_result(result)
    execution.status = (
        ExecutionStatus.COMPLETED
        if result.status == "completed"
        else ExecutionStatus.FAILED
    )
    if result.status != "completed" and not execution.failure_code:
        execution.failure_code = "PIPELINE_NODE_FAILED"
    execution.duration_ms = result.total_duration_ms
    execution.completed_at = datetime.now(timezone.utc)
    if result.final_output:
        out = result.final_output
        if isinstance(out, (dict, list)):
            try:
                out = json.dumps(out, default=str)
            except (TypeError, ValueError):
                out = str(out)
        execution.output_message = str(out)[:50000]

    # Store node_results and execution_trace for the flight recorder
    execution.node_results = serialized.get("node_results")
    execution.execution_trace = {
        "pipeline_status": result.status,
        "execution_path": result.execution_path,
        "failed_nodes": result.failed_nodes,
        "skipped_nodes": getattr(result, "skipped_nodes", []),
        "node_results": serialized.get("node_results"),
    }
    await db.commit()

    # Drift detection for pipeline executions (gated by env + tenant + agent)
    try:
        from app.core.config import settings

        _ag_q = await db.execute(select(Agent).where(Agent.id == execution.agent_id))
        _ag = _ag_q.scalar_one_or_none()
        if _ag and await _drift_enabled(_ag):
            # Aggregate per-node counters across the pipeline
            _total_in = 0
            _total_out = 0
            _total_cost = 0.0
            _tool_fails = 0
            _tool_calls = 0
            for _nid, _nr in (serialized.get("node_results") or {}).items():
                o = _nr.get("output") if isinstance(_nr, dict) else None
                if isinstance(o, dict):
                    _total_in += int(o.get("input_tokens", 0) or 0)
                    _total_out += int(o.get("output_tokens", 0) or 0)
                    _total_cost += float(o.get("cost", 0) or 0)
                    _tool_calls += int(o.get("tool_calls_count", 1) or 1)
                    if _nr.get("status") == "failed":
                        _tool_fails += 1
            from engine.drift_detection import DriftDetector

            detector = DriftDetector(redis_url=str(settings.redis_url))
            _alerts = await detector.record_execution(
                agent_id=str(execution.agent_id),
                duration_ms=int(result.total_duration_ms or 0),
                input_tokens=_total_in,
                output_tokens=_total_out,
                cost=_total_cost,
                confidence=1.0,
                output_length=len(execution.output_message or ""),
                tool_failures=_tool_fails,
                total_tool_calls=max(_tool_calls, 1),
            )
            await _persist_drift_alerts(db, _alerts, _ag, str(execution.id))
    except Exception:
        pass

    # Complete live state
    await complete_state(str(execution.id), tenant_id)

    serialized["execution_id"] = str(execution.id)
    # Expose the final_output under the same `output` key that the
    # queue-mode path uses. Callers (SDKs, standalone apps) should not
    # have to fish through node_results to find the terminal node's
    # payload — that's the whole point of the pipeline.
    serialized["output"] = result.final_output
    serialized["cost"] = _total_cost if "_total_cost" in locals() else 0.0
    serialized["duration_ms"] = int(result.total_duration_ms or 0)
    return success(serialized)


async def _fetch_mcp_connections(
    db: AsyncSession,
    agent_id: uuid.UUID,
) -> list[dict[str, Any]]:
    """Fetch MCP server connections attached to an agent for tool resolution."""
    result = await db.execute(
        select(AgentMCPTool).where(AgentMCPTool.agent_id == agent_id)
    )
    agent_tools = result.scalars().all()
    if not agent_tools:
        return []

    conn_ids = {t.mcp_connection_id for t in agent_tools}
    conn_result = await db.execute(
        select(UserMCPConnection).where(
            UserMCPConnection.id.in_(conn_ids),
            UserMCPConnection.is_enabled,
        )
    )
    connections = {c.id: c for c in conn_result.scalars().all()}

    mcp_conns: dict[str, dict[str, Any]] = {}
    for tool in agent_tools:
        conn = connections.get(tool.mcp_connection_id)
        if not conn:
            continue
        key = str(conn.id)
        if key not in mcp_conns:
            mcp_conns[key] = {
                "server_url": conn.server_url,
                "auth_type": conn.auth_type,
                "auth_config": conn.auth_config or {},
                "tools": [],
            }
        mcp_conns[key]["tools"].append(tool.tool_name)

    return list(mcp_conns.values())


async def _stream_execution(
    execution_id: uuid.UUID,
    agent_id: uuid.UUID,
    message: str,
    system_prompt: str,
    model: str,
    temperature: float,
    tool_names: list[str],
    mcp_connections: list[dict[str, Any]],
    db: AsyncSession,
    enterprise_ctx: dict[str, Any] | None = None,
    user_context: dict[str, Any] | None = None,
    kb_ids: list[str] | None = None,
    max_iterations: int | None = None,
    max_tokens: int = 4096,
    cache_enabled: bool = True,
) -> Any:
    import os as _os
    from app.core.config import settings

    # Inject user context (input variables) into the message for the LLM
    if user_context:
        context_lines = "\n".join(f"  {k}: {v}" for k, v in user_context.items())
        message = f"{message}\n\n[Input Parameters provided by user]\n{context_lines}"

    enterprise_ctx = enterprise_ctx or {}
    tenant_id = enterprise_ctx.get("tenant_id", "")
    agent_name = enterprise_ctx.get("agent_name", "")
    acting_subject = enterprise_ctx.get("acting_subject")
    agent_model_config = enterprise_ctx.get("model_config") or {}

    # Build tool registry with enterprise context for memory/HITL tools
    registry_kwargs = dict(
        agent_id=str(agent_id),
        tenant_id=tenant_id,
        execution_id=str(execution_id),
        agent_name=agent_name,
        db_url=str(settings.database_url),
        acting_subject=acting_subject,
        model_config=agent_model_config,
    )

    # Publish live execution state to Redis
    try:
        from app.core.execution_state import publish_state, complete_state, fail_state

        await publish_state(
            str(execution_id), tenant_id, str(agent_id), agent_name, "running"
        )
    except Exception:
        pass  # Graceful degradation if Redis unavailable

    full_output = ""
    all_tool_calls: list[dict[str, Any]] = []
    final_data: dict[str, Any] = {}
    mcp_clients: list = []

    runtime_mode = _os.environ.get("RUNTIME_MODE", "embedded").lower()

    if runtime_mode == "remote":
        from engine.execution_router import stream_agent, ExecutionConfig

        exec_config = ExecutionConfig(
            message=message,
            system_prompt=system_prompt,
            model=model,
            temperature=temperature,
            tool_names=tool_names,
            agent_id=str(agent_id),
            tenant_id=tenant_id,
            execution_id=str(execution_id),
            agent_name=agent_name,
            db_url=os.environ.get("DATABASE_URL", ""),
            kb_ids=kb_ids,
            model_config=agent_model_config,
        )
        event_source = stream_agent(exec_config)
    else:
        from engine.llm_router import LLMRouter

        if mcp_connections:
            from engine.tool_resolver import resolve_tools
            from engine.agent_executor import AgentExecutor

            tool_registry, mcp_clients, _sec_ctx = await resolve_tools(
                tool_names, mcp_connections
            )
        else:
            from engine.agent_executor import AgentExecutor, build_tool_registry

            tool_registry = build_tool_registry(
                tool_names, kb_ids=kb_ids, **registry_kwargs
            )

        llm_router = LLMRouter()

        # Build moderation gate from tenant's active policy (if any).
        # _stream_execution doesn't get a `user` reference — the caller
        # threads tenant_id + user_id through enterprise_ctx so we can
        # build the gate without a DB round-trip on the user.
        from app.core.moderation_glue import (
            build_gate_context,
            persist_events as _mod_persist,
        )

        _mod_ctx = None
        try:
            _user_id_str = enterprise_ctx.get("user_id") or ""
            if tenant_id and _user_id_str:
                _mod_ctx = await build_gate_context(
                    db,
                    uuid.UUID(tenant_id),
                    uuid.UUID(_user_id_str),
                )
        except Exception as _mod_exc:
            import logging as _log

            _log.getLogger(__name__).warning(
                "moderation gate build failed: %s", _mod_exc
            )
            _mod_ctx = None

        # Resolve asset input_schemas async, BEFORE constructing the
        # executor — the agent_runtime image doesn't ship psycopg2 so
        # this has to be awaited, not called from sync __init__.
        from engine.agent_executor import resolve_asset_schemas as _ras

        _tool_cfg = agent_model_config.get("tool_config") or {}
        _asset_schemas = await _ras(_tool_cfg)

        _exec_kwargs = dict(
            llm_router=llm_router,
            tool_registry=tool_registry,
            system_prompt=system_prompt,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            cache=_get_cache_orchestrator() if cache_enabled else None,
            agent_id=str(agent_id),
            execution_id=str(execution_id),
            moderation_gate=(_mod_ctx.gate if _mod_ctx else None),
            # Pass the agent's tool_config so the executor can strip
            # parameter_defaults from the LLM-visible tool schemas
            # and merge them back in at dispatch. Fixes the LLM
            # hallucinating code_asset_id / model_id.
            tool_config=_tool_cfg,
            asset_schemas=_asset_schemas,
        )
        if max_iterations:
            _exec_kwargs["max_iterations"] = int(max_iterations)
        executor = AgentExecutor(**_exec_kwargs)

        async def _embedded_events():
            async for evt in executor.stream(message):
                yield {"event": evt.event, "data": evt.data}

        event_source = _embedded_events()

    try:
        async for event in event_source:
            event_type = event.get("event", "")
            event_data = event.get("data", {})

            if event_type == "token":
                text = (
                    event_data
                    if isinstance(event_data, str)
                    else event_data.get("text", event_data.get("content", ""))
                )
                full_output += text
                yield f"event: token\ndata: {json.dumps({'text': text})}\n\n"
            elif event_type == "tool_call":
                all_tool_calls.append(
                    event_data if isinstance(event_data, dict) else {}
                )
                yield f"event: tool_call\ndata: {json.dumps(event_data, default=str)}\n\n"
                # Update live state with current tool
                try:
                    tool_name = (
                        event_data.get("name", "")
                        if isinstance(event_data, dict)
                        else ""
                    )
                    await publish_state(
                        str(execution_id),
                        tenant_id,
                        str(agent_id),
                        agent_name,
                        "running",
                        tool_name,
                    )
                except Exception:
                    pass
            elif event_type == "tool_result":
                yield f"event: tool_result\ndata: {json.dumps(event_data, default=str)}\n\n"
            elif event_type == "node_trace":
                yield f"event: node_trace\ndata: {json.dumps(event_data, default=str)}\n\n"
            elif event_type == "done":
                final_data = event_data if isinstance(event_data, dict) else {}
                # Calculate confidence score
                try:
                    from engine.confidence import (
                        ConfidenceFactors,
                        calculate_confidence,
                    )

                    failed_tools = sum(1 for tc in all_tool_calls if tc.get("is_error"))
                    factors = ConfidenceFactors(
                        total_tool_calls=len(all_tool_calls),
                        failed_tool_calls=failed_tools,
                        output_length=len(full_output),
                        input_length=len(message),
                    )
                    confidence = calculate_confidence(factors)
                    final_data["confidence_score"] = confidence
                except Exception:
                    confidence = None
                yield f"event: done\ndata: {json.dumps(final_data)}\n\n"
            elif event_type == "error":
                err_msg = (
                    event_data.get("message", str(event_data))
                    if isinstance(event_data, dict)
                    else str(event_data)
                )
                yield f"event: error\ndata: {json.dumps({'message': err_msg})}\n\n"

        # Cleanup MCP clients if embedded mode
        for client in mcp_clients:
            try:
                await client.close()
            except Exception:
                pass

        result = await db.execute(select(Execution).where(Execution.id == execution_id))
        execution = result.scalar_one_or_none()
        if execution:
            # Persist any moderation events captured during streaming.
            try:
                if _mod_ctx is not None and _mod_ctx.gate is not None:
                    await _mod_persist(
                        db, execution.tenant_id, execution.user_id, _mod_ctx
                    )
            except Exception:
                pass

            # Detect a moderation block from the final `done` payload
            # — the streaming executor sets error="moderation_blocked"
            # and includes moderation_blocked=True. Surface as FAILED
            # with failure_code=MODERATION_BLOCKED so the UI groups it.
            _mod_blocked = bool(final_data.get("moderation_blocked")) or (
                final_data.get("error") == "moderation_blocked"
            )
            if _mod_blocked:
                from app.core.failure_codes import emit_outcome_metric

                execution.status = ExecutionStatus.FAILED
                execution.failure_code = "MODERATION_BLOCKED"
                execution.error_message = (
                    full_output or "Moderation policy blocked the request"
                )[:2000]
                execution.output_message = full_output
                execution.input_tokens = final_data.get("input_tokens") or 0
                execution.output_tokens = final_data.get("output_tokens") or 0
                execution.cost = float(final_data.get("cost") or 0.0)
                execution.duration_ms = final_data.get("duration_ms")
                execution.tool_calls = all_tool_calls if all_tool_calls else None
                execution.completed_at = datetime.now(timezone.utc)
                try:
                    emit_outcome_metric(
                        outcome="FAILED",
                        failure_code="MODERATION_BLOCKED",
                        agent_type="agent",
                    )
                except Exception:
                    pass
            else:
                execution.status = ExecutionStatus.COMPLETED
                execution.output_message = full_output
                execution.input_tokens = final_data.get("input_tokens")
                execution.output_tokens = final_data.get("output_tokens")
                execution.cost = final_data.get("cost")
                execution.duration_ms = final_data.get("duration_ms")
                execution.tool_calls = all_tool_calls if all_tool_calls else None
                execution.completed_at = datetime.now(timezone.utc)

            # Store confidence score and execution trace
            if hasattr(execution, "confidence_score"):
                execution.confidence_score = final_data.get("confidence_score")
            if hasattr(execution, "execution_trace"):
                execution.execution_trace = {
                    "tool_calls": all_tool_calls,
                    "confidence_score": final_data.get("confidence_score"),
                    "model": model,
                    "temperature": temperature,
                }

            from app.core.usage import track_execution, update_user_usage

            await track_execution(
                db,
                tenant_id=execution.tenant_id,
                user_id=execution.user_id,
                agent_id=execution.agent_id,
                input_tokens=final_data.get("input_tokens", 0) or 0,
                output_tokens=final_data.get("output_tokens", 0) or 0,
                cost=float(final_data.get("cost", 0) or 0),
            )
            # Update user usage counters
            user_result = await db.execute(
                select(User).where(User.id == execution.user_id)
            )
            _exec_user = user_result.scalar_one_or_none()
            if _exec_user:
                await update_user_usage(
                    db,
                    _exec_user,
                    final_data.get("input_tokens", 0) or 0,
                    final_data.get("output_tokens", 0) or 0,
                    float(final_data.get("cost", 0) or 0),
                )
            await db.commit()

            # Record drift detection data (gated by env + tenant + per-agent toggle)
            try:
                _agent_q = await db.execute(select(Agent).where(Agent.id == agent_id))
                _agent_for_drift = _agent_q.scalar_one_or_none()
                if _agent_for_drift and await _drift_enabled(_agent_for_drift):
                    from engine.drift_detection import DriftDetector

                    detector = DriftDetector(redis_url=str(settings.redis_url))
                    _drift_alerts = await detector.record_execution(
                        agent_id=str(agent_id),
                        duration_ms=final_data.get("duration_ms", 0) or 0,
                        input_tokens=final_data.get("input_tokens", 0) or 0,
                        output_tokens=final_data.get("output_tokens", 0) or 0,
                        cost=float(final_data.get("cost", 0) or 0),
                        confidence=final_data.get("confidence_score", 1.0) or 1.0,
                        output_length=len(full_output),
                        tool_failures=sum(
                            1 for tc in all_tool_calls if tc.get("is_error")
                        ),
                        total_tool_calls=len(all_tool_calls),
                    )
                    await _persist_drift_alerts(
                        db,
                        _drift_alerts,
                        _agent_for_drift,
                        str(execution_id),
                    )
            except Exception:
                pass  # Graceful degradation

            # Mark live execution complete
            try:
                await complete_state(str(execution_id), tenant_id)
            except Exception:
                pass

            await _emit_execution_event(
                db,
                execution,
                "execution_complete",
                cost=final_data.get("cost"),
                duration_ms=final_data.get("duration_ms"),
            )

    except Exception as e:
        yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"

        result = await db.execute(select(Execution).where(Execution.id == execution_id))
        execution = result.scalar_one_or_none()
        if execution:
            execution.status = ExecutionStatus.FAILED
            execution.error_message = str(e)
            execution.completed_at = datetime.now(timezone.utc)
            await db.commit()

            # Mark live execution failed
            try:
                await fail_state(str(execution_id), tenant_id, str(e))
            except Exception:
                pass

            await _emit_execution_event(
                db,
                execution,
                "execution_failed",
                error_message=str(e),
            )
    finally:
        for client in mcp_clients:
            await client.close()


async def _non_stream_execution(
    execution: Execution,
    message: str,
    system_prompt: str,
    model: str,
    temperature: float,
    tool_names: list[str],
    mcp_connections: list[dict[str, Any]],
    db: AsyncSession,
    enterprise_ctx: dict[str, Any] | None = None,
    user_context: dict[str, Any] | None = None,
    kb_ids: list[str] | None = None,
    max_iterations: int | None = None,
    max_tokens: int = 4096,
    cache_enabled: bool = True,
    tool_config: dict[str, dict[str, Any]] | None = None,
) -> JSONResponse:
    from engine.llm_router import LLMRouter
    from app.core.config import settings

    enterprise_ctx = enterprise_ctx or {}

    # Inject user context (input variables) into the message for the LLM
    if user_context:
        context_lines = "\n".join(f"  {k}: {v}" for k, v in user_context.items())
        message = f"{message}\n\n[Input Parameters provided by user]\n{context_lines}"
    tenant_id = enterprise_ctx.get("tenant_id", "")
    agent_name = enterprise_ctx.get("agent_name", "")
    acting_subject = enterprise_ctx.get("acting_subject")

    llm_router = LLMRouter()

    registry_kwargs = dict(
        agent_id=str(execution.agent_id),
        tenant_id=tenant_id,
        execution_id=str(execution.id),
        agent_name=agent_name,
        db_url=str(settings.database_url),
        acting_subject=acting_subject,
    )

    mcp_clients = []
    if mcp_connections:
        from engine.tool_resolver import resolve_tools
        from engine.agent_executor import AgentExecutor

        tool_registry, mcp_clients, _sec_ctx = await resolve_tools(
            tool_names, mcp_connections
        )
    else:
        from engine.agent_executor import AgentExecutor, build_tool_registry

        tool_registry = build_tool_registry(
            tool_names, kb_ids=kb_ids, **registry_kwargs
        )

    # Load tenant moderation policy for the non-streaming path too.
    from app.core.moderation_glue import build_gate_context, persist_events

    _mod_ctx2 = await build_gate_context(
        db,
        execution.tenant_id,
        execution.user_id,
    )

    # Resolve asset input_schemas async, matching the streaming path.
    from engine.agent_executor import resolve_asset_schemas as _ras

    _tc_nonstream = tool_config or {}
    _asset_schemas_ns = await _ras(_tc_nonstream)

    _exec_kwargs2 = dict(
        llm_router=llm_router,
        tool_registry=tool_registry,
        system_prompt=system_prompt,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        cache=_get_cache_orchestrator() if cache_enabled else None,
        agent_id=str(execution.agent_id),
        execution_id=str(execution.id),
        moderation_gate=_mod_ctx2.gate,
        # Same tool-schema injection as the streaming path — strips
        # parameter_defaults from the LLM-visible schemas and merges
        # them back at dispatch. Keep the two code paths symmetric.
        tool_config=_tc_nonstream,
        asset_schemas=_asset_schemas_ns,
    )
    if max_iterations:
        _exec_kwargs2["max_iterations"] = int(max_iterations)
    executor = AgentExecutor(**_exec_kwargs2)

    # Publish live execution state
    try:
        from app.core.execution_state import publish_state, complete_state, fail_state

        await publish_state(
            str(execution.id), tenant_id, str(execution.agent_id), agent_name, "running"
        )
    except Exception:
        pass

    try:
        result = await executor.invoke(message)

        # Persist any moderation events the gate captured during the run
        # — regardless of outcome, we record them for audit.
        try:
            if _mod_ctx2.gate is not None:
                await persist_events(
                    db, execution.tenant_id, execution.user_id, _mod_ctx2
                )
        except Exception:
            pass

        # Calculate confidence score
        confidence = None
        try:
            from engine.confidence import ConfidenceFactors, calculate_confidence

            failed_tools = sum(
                1 for tc in (result.tool_calls or []) if tc.get("is_error")
            )
            factors = ConfidenceFactors(
                total_tool_calls=len(result.tool_calls or []),
                failed_tool_calls=failed_tools,
                output_length=len(result.output or ""),
                input_length=len(message),
            )
            confidence = calculate_confidence(factors)
        except Exception:
            pass

        # Moderation block becomes a FAILED execution with a distinct
        # failure_code so dashboards + alerts can group it cleanly.
        if getattr(result, "moderation_blocked", False):
            from app.core.failure_codes import emit_outcome_metric

            execution.status = ExecutionStatus.FAILED
            execution.failure_code = "MODERATION_BLOCKED"
            execution.error_message = (
                result.output[:2000]
                if result.output
                else f"Moderation policy blocked at {result.moderation_block_source}"
            )
            execution.output_message = result.output
            execution.input_tokens = result.input_tokens
            execution.output_tokens = result.output_tokens
            execution.cost = float(result.cost)
            execution.duration_ms = result.duration_ms
            execution.completed_at = datetime.now(timezone.utc)
            emit_outcome_metric(
                outcome="FAILED",
                failure_code="MODERATION_BLOCKED",
                agent_type="agent",
            )
        else:
            execution.status = ExecutionStatus.COMPLETED
            execution.output_message = result.output
            execution.input_tokens = result.input_tokens
            execution.output_tokens = result.output_tokens
            execution.cost = float(result.cost)
            execution.duration_ms = result.duration_ms
            execution.tool_calls = result.tool_calls if result.tool_calls else None
            execution.completed_at = datetime.now(timezone.utc)

        # Store confidence and execution trace
        if hasattr(execution, "confidence_score") and confidence is not None:
            execution.confidence_score = confidence
        if hasattr(execution, "execution_trace"):
            node_traces = (
                [t.to_dict() for t in result.node_traces] if result.node_traces else []
            )
            execution.execution_trace = {
                "steps": node_traces,
                "tool_calls": result.tool_calls,
                "confidence_score": confidence,
            }

        from app.core.usage import track_execution, update_user_usage

        await track_execution(
            db,
            tenant_id=execution.tenant_id,
            user_id=execution.user_id,
            agent_id=execution.agent_id,
            input_tokens=result.input_tokens or 0,
            output_tokens=result.output_tokens or 0,
            cost=float(result.cost or 0),
        )
        # Update user usage counters
        user_result_q = await db.execute(
            select(User).where(User.id == execution.user_id)
        )
        _exec_user = user_result_q.scalar_one_or_none()
        if _exec_user:
            await update_user_usage(
                db,
                _exec_user,
                result.input_tokens or 0,
                result.output_tokens or 0,
                float(result.cost or 0),
            )
        await db.commit()

        # Drift detection (gated by env + per-agent toggle)
        try:
            _agent_q = await db.execute(
                select(Agent).where(Agent.id == execution.agent_id)
            )
            _agent_for_drift = _agent_q.scalar_one_or_none()
            if not _agent_for_drift or not await _drift_enabled(_agent_for_drift):
                raise _StopDrift()
            from engine.drift_detection import DriftDetector

            detector = DriftDetector(redis_url=str(settings.redis_url))
            _drift_alerts = await detector.record_execution(
                agent_id=str(execution.agent_id),
                duration_ms=result.duration_ms or 0,
                input_tokens=result.input_tokens or 0,
                output_tokens=result.output_tokens or 0,
                cost=float(result.cost or 0),
                confidence=confidence or 1.0,
                output_length=len(result.output or ""),
                tool_failures=sum(
                    1 for tc in (result.tool_calls or []) if tc.get("is_error")
                ),
                total_tool_calls=len(result.tool_calls or []),
            )
            await _persist_drift_alerts(
                db, _drift_alerts, _agent_for_drift, str(execution.id)
            )
        except Exception:
            pass

        # Mark live execution complete
        try:
            await complete_state(str(execution.id), tenant_id)
        except Exception:
            pass

        await _emit_execution_event(
            db,
            execution,
            "execution_complete",
            cost=result.cost,
            duration_ms=result.duration_ms,
        )

        node_traces_out = (
            [t.to_dict() for t in result.node_traces] if result.node_traces else []
        )

        return success(
            {
                "execution_id": str(execution.id),
                "output": result.output,
                "model": result.model,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "cost": round(result.cost, 6),
                "duration_ms": result.duration_ms,
                "tool_calls": result.tool_calls,
                "node_traces": node_traces_out,
                "confidence_score": confidence,
            }
        )

    except Exception as e:
        execution.status = ExecutionStatus.FAILED
        execution.error_message = str(e)[:2000]
        # Classify exception → stable failure_code for dashboards/alerts.
        from app.core.failure_codes import classify_exception, emit_outcome_metric

        execution.failure_code = classify_exception(e)
        execution.completed_at = datetime.now(timezone.utc)
        emit_outcome_metric(outcome="FAILED", failure_code=execution.failure_code)
        await db.commit()

        try:
            await fail_state(str(execution.id), tenant_id, str(e))
        except Exception:
            pass

        await _emit_execution_event(
            db,
            execution,
            "execution_failed",
            error_message=str(e),
        )

        return error(f"Execution failed: {str(e)}", 500)
    finally:
        for client in mcp_clients:
            await client.close()


async def _emit_execution_event(
    db: AsyncSession,
    execution: Execution,
    event_type: str,
    cost: float | None = None,
    duration_ms: int | None = None,
    error_message: str | None = None,
) -> None:
    agent_result = await db.execute(
        select(Agent.name).where(Agent.id == execution.agent_id)
    )
    agent_name = agent_result.scalar() or "Agent"

    event_data = {
        "execution_id": str(execution.id),
        "agent_id": str(execution.agent_id),
        "agent_name": agent_name,
    }

    if event_type == "execution_complete":
        title = f"{agent_name} completed"
        message = f"Execution finished in {duration_ms or 0}ms"
        if cost:
            message += f" (${cost:.4f})"
        event_data["cost"] = float(cost) if cost else 0
        event_data["duration_ms"] = duration_ms
    else:
        title = f"{agent_name} failed"
        message = error_message or "Execution failed"
        event_data["error"] = error_message

    await ws_manager.send_to_user(
        execution.user_id,
        event_type,
        event_data,
    )

    await ws_manager.send_to_user(
        execution.user_id,
        "dashboard_update",
        {"trigger": event_type},
    )

    try:
        await create_notification(
            db,
            tenant_id=execution.tenant_id,
            user_id=execution.user_id,
            type=event_type,
            title=title,
            message=message,
            link=f"/agents/{execution.agent_id}/chat",
            metadata=event_data,
        )
        await db.commit()
    except Exception:
        pass

    # Deliver webhooks for execution events
    try:
        from app.core.webhooks import deliver_execution_webhook

        webhook_event = (
            "execution.completed"
            if event_type == "execution_complete"
            else "execution.failed"
        )
        await deliver_execution_webhook(
            db,
            str(execution.tenant_id),
            webhook_event,
            event_data,
        )
    except Exception:
        pass
