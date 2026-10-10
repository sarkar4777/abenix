from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import String, cast, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.permissions import is_admin
from app.core.responses import success
from models.user import User

router = APIRouter(prefix="/api/search", tags=["search"])
logger = logging.getLogger(__name__)


# Static catalogue of in-app routes. Spotlight matches against label + keywords
# and returns href so the client can router.push() straight to the page.
_ROUTES: list[dict[str, Any]] = [
    # PINNED
    {
        "label": "Dashboard",
        "href": "/dashboard",
        "keywords": "home overview metrics live pinned",
    },
    {"label": "My Agents", "href": "/agents", "keywords": "agent list bot pinned"},
    {"label": "AI Chat", "href": "/chat", "keywords": "chat conversation ask pinned"},
    {
        "label": "Alerts",
        "href": "/alerts",
        "keywords": "alert failure error grouped pinned",
    },
    # BUILD
    {
        "label": "Agent Builder",
        "href": "/builder",
        "keywords": "create new build agent workflow pipeline canvas",
    },
    {
        "label": "Tools Catalogue",
        "href": "/tools",
        "keywords": "tool list catalog build",
    },
    {
        "label": "Code Runner",
        "href": "/code-runner",
        "keywords": "code asset runner execute repo build go python java",
    },
    {
        "label": "ML Models",
        "href": "/ml-models",
        "keywords": "ml model train deploy onnx pytorch build",
    },
    {
        "label": "Knowledge Bases",
        "href": "/knowledge",
        "keywords": "knowledge document corpus retrieval rag build",
    },
    {"label": "Persona KB", "href": "/persona", "keywords": "persona profile build"},
    {
        "label": "Portfolio Schemas",
        "href": "/portfolio-schemas",
        "keywords": "schema json output build",
    },
    {
        "label": "BPM Analyzer",
        "href": "/bpm-analyzer",
        "keywords": "bpmn process analyzer build",
    },
    {"label": "Atlas", "href": "/atlas", "keywords": "atlas graph map knowledge build"},
    # RUN & TEST
    {
        "label": "SDK Playground",
        "href": "/sdk-playground",
        "keywords": "sdk playground try test",
    },
    {
        "label": "Load Playground",
        "href": "/load-playground",
        "keywords": "load test bench performance run",
    },
    {
        "label": "Triggers",
        "href": "/triggers",
        "keywords": "trigger schedule cron webhook run",
    },
    # MONITOR
    {
        "label": "Observability Hub",
        "href": "/observability",
        "keywords": "trace tempo grafana telemetry phase monitor observability",
    },
    {
        "label": "Executions",
        "href": "/executions",
        "keywords": "execution run history log activity monitor",
    },
    {
        "label": "Live Debug",
        "href": "/executions/live",
        "keywords": "live debug stream monitor",
    },
    {
        "label": "Analytics",
        "href": "/analytics",
        "keywords": "analytics chart cost token usage monitor",
    },
    {
        "label": "Moderation",
        "href": "/moderation",
        "keywords": "moderation safety policy guardrail monitor",
    },
    # MONETIZE
    {
        "label": "Marketplace",
        "href": "/marketplace",
        "keywords": "marketplace store buy",
    },
    {
        "label": "Creator Hub",
        "href": "/creator",
        "keywords": "creator earnings revenue payouts",
    },
    # ADMIN
    {
        "label": "Cluster Health",
        "href": "/admin/cluster",
        "keywords": "cluster kubernetes pod memory disk db database health resource admin",
    },
    {
        "label": "Scaling",
        "href": "/admin/scaling",
        "keywords": "scaling pool keda autoscale admin",
    },
    {
        "label": "Archives",
        "href": "/admin/archives",
        "keywords": "archive backup rotation admin",
    },
    {
        "label": "Model Selection",
        "href": "/admin/llm-settings",
        "keywords": "llm model selection routing admin",
    },
    {
        "label": "LLM Pricing",
        "href": "/admin/llm-pricing",
        "keywords": "pricing cost token rate admin",
    },
    {"label": "Connectors", "href": "/admin/connectors", "keywords": "connector admin"},
    {
        "label": "Dead Letter Queue",
        "href": "/admin/dlq",
        "keywords": "dlq dead letter queue retry admin",
    },
    {
        "label": "Review Queue",
        "href": "/review-queue",
        "keywords": "review queue approval admin",
    },
    {
        "label": "Team",
        "href": "/settings/team",
        "keywords": "team member user role rbac admin",
    },
    # WORKSPACE
    {
        "label": "Approvals",
        "href": "/approvals",
        "keywords": "approval gate human review hitl workspace",
    },
    {
        "label": "MCP Servers",
        "href": "/mcp",
        "keywords": "mcp model context protocol workspace",
    },
    {"label": "Edge", "href": "/edge", "keywords": "edge runtime workspace"},
    {
        "label": "API Keys",
        "href": "/settings/api-keys",
        "keywords": "api key token credential workspace",
    },
    {
        "label": "Integrations",
        "href": "/settings/integrations",
        "keywords": "integration connector workspace",
    },
    {
        "label": "Settings",
        "href": "/settings",
        "keywords": "settings preference config workspace",
    },
    {
        "label": "Settings — Profile",
        "href": "/settings/profile",
        "keywords": "profile avatar name workspace",
    },
    {
        "label": "Settings — Security",
        "href": "/settings/security",
        "keywords": "security 2fa password workspace",
    },
    {
        "label": "Settings — Billing",
        "href": "/settings/billing",
        "keywords": "billing plan subscription payment workspace",
    },
    {
        "label": "Settings — Notifications",
        "href": "/settings/notifications",
        "keywords": "notification email slack alert workspace",
    },
    {
        "label": "Settings — Quotas",
        "href": "/settings/quotas",
        "keywords": "quota limit rate workspace",
    },
    {
        "label": "Settings — Webhooks",
        "href": "/settings/webhooks",
        "keywords": "webhook callback workspace",
    },
    {
        "label": "Settings — Observability",
        "href": "/settings/observability",
        "keywords": "settings observability workspace",
    },
    {
        "label": "Settings — Sandbox",
        "href": "/settings/sandbox",
        "keywords": "sandbox settings workspace",
    },
    {
        "label": "Settings — Privacy",
        "href": "/settings/privacy",
        "keywords": "privacy gdpr workspace",
    },
    {
        "label": "Settings — Data",
        "href": "/settings/data",
        "keywords": "data export retention workspace",
    },
    {"label": "Help", "href": "/help", "keywords": "help docs walkthrough workspace"},
    {
        "label": "Meetings",
        "href": "/meetings",
        "keywords": "meeting calendar workspace",
    },
    # Other top-level
    {"label": "Webhooks", "href": "/webhooks", "keywords": "webhook list workspace"},
    {
        "label": "OracleNet",
        "href": "/oraclenet",
        "keywords": "oraclenet research synthesis",
    },
    {"label": "Docs", "href": "/docs", "keywords": "documentation api reference"},
]


@router.get("")
async def search(
    q: str = Query(..., min_length=1, max_length=80, description="Query string"),
    limit: int = Query(8, ge=1, le=20, description="Max results per category"),
    archived: int = Query(0, ge=0, le=1, description="Include archived decisions"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Spotlight-style global search across pages, agents, pipelines,
    runs, knowledge bases, ML models, code assets, limited to what the caller can open.

    Returns a unified result list with category + label + href so the
    client can navigate straight to the matching surface.
    """
    needle = q.strip().lower()
    out: list[dict[str, Any]] = []

    # 1. Pages — substring on label + keywords
    market_on: bool | None = None
    for row in _ROUTES:
        hay = f"{row['label']} {row.get('keywords', '')}".lower()
        if needle in hay and row["href"] in ("/marketplace", "/creator"):
            if market_on is None:
                from app.core.platform_features import marketplace_enabled

                market_on = await marketplace_enabled(db)
            if not market_on:
                continue
        if needle in hay:
            out.append(
                {
                    "category": "Pages",
                    "label": row["label"],
                    "subtitle": row["href"],
                    "href": row["href"],
                }
            )
            if sum(1 for x in out if x["category"] == "Pages") >= limit:
                break

    tenant_id = user.tenant_id

    like = f"%{needle}%"
    admin = is_admin(user)

    # decisions by name, key or description, for people who can see decisions
    try:
        from app.core.capabilities import has_capability
        from app.routers.decisions import search_terms
        from models.decision import DecisionModel

        if await has_capability(db, user, "decisions.view"):
            stmt = select(
                DecisionModel.key, DecisionModel.name, DecisionModel.archived_at
            ).where(DecisionModel.tenant_id == tenant_id, *search_terms(q))
            if not archived:
                stmt = stmt.where(DecisionModel.archived_at.is_(None))
            for r in (
                await db.execute(stmt.order_by(DecisionModel.name).limit(limit))
            ).all():
                out.append(
                    {
                        "category": "Decisions",
                        "label": r.name,
                        "subtitle": r.key + (" (archived)" if r.archived_at else ""),
                        "href": f"/decisions/{r.key}",
                    }
                )
    except Exception:
        logger.exception("search: decisions failed")

    # 2. Agents and pipelines the caller can open, platform ones included
    try:
        from app.services.agent_share import accessible_agent_ids
        from models.agent import Agent, AgentStatus, AgentType

        stmt = select(
            Agent.id, Agent.name, Agent.description, Agent.model_config_
        ).where(
            Agent.status != AgentStatus.ARCHIVED,
            or_(Agent.name.ilike(like), Agent.description.ilike(like)),
        )
        if admin:
            stmt = stmt.where(
                or_(Agent.tenant_id == tenant_id, Agent.agent_type == AgentType.OOB)
            )
        else:
            mine = await accessible_agent_ids(db, user)
            stmt = stmt.where(
                or_(
                    Agent.agent_type == AgentType.OOB,
                    Agent.id.in_(mine or [uuid.UUID(int=0)]),
                )
            )
        rows = (await db.execute(stmt.order_by(Agent.name).limit(limit * 2))).all()
        counts: dict[str, int] = {}
        for r in rows:
            cat = (
                "Pipelines"
                if (r.model_config_ or {}).get("mode") == "pipeline"
                else "Agents"
            )
            if counts.get(cat, 0) >= limit:
                continue
            counts[cat] = counts.get(cat, 0) + 1
            out.append(
                {
                    "category": cat,
                    "label": r.name,
                    "subtitle": (r.description or "")[:120],
                    "href": f"/agents/{r.id}/info",
                }
            )
    except Exception:
        logger.exception("search: agents failed")

    # 3. Knowledge bases the caller can read
    try:
        from app.services.kb_access import accessible_collection_ids
        from models.knowledge_base import KnowledgeBase

        stmt = select(
            KnowledgeBase.id, KnowledgeBase.name, KnowledgeBase.description
        ).where(
            KnowledgeBase.tenant_id == tenant_id,
            or_(KnowledgeBase.name.ilike(like), KnowledgeBase.description.ilike(like)),
        )
        allowed = await accessible_collection_ids(db, user=user, tenant_id=tenant_id)
        if allowed is not None:
            stmt = stmt.where(KnowledgeBase.id.in_(allowed or [uuid.UUID(int=0)]))
        for r in (await db.execute(stmt.limit(limit))).all():
            out.append(
                {
                    "category": "Knowledge",
                    "label": r.name,
                    "subtitle": (r.description or "")[:120],
                    "href": f"/knowledge?id={r.id}",
                }
            )
    except Exception:
        logger.exception("search: knowledge failed")

    # 4. ML models and code assets, own, shared or the whole tenant for admins
    for kind, module, cls, cat, href in (
        ("ml_model", "models.ml_model", "MLModel", "ML Models", "/ml-models?id={}"),
        (
            "code_asset",
            "models.code_asset",
            "CodeAsset",
            "Code Assets",
            "/code-runner?asset={}",
        ),
    ):
        try:
            import importlib

            from app.core.permissions import (
                accessible_resource_ids,
                apply_resource_scope,
            )

            model = getattr(importlib.import_module(module), cls)
            stmt = select(model.id, model.name, model.description).where(
                or_(model.name.ilike(like), model.description.ilike(like))
            )
            stmt = apply_resource_scope(
                stmt,
                model,
                user,
                kind=kind,
                accessible_ids=await accessible_resource_ids(db, user, kind=kind),
            )
            if hasattr(model, "status"):
                stmt = stmt.where(cast(model.status, String) != "deleted")
            for r in (await db.execute(stmt.limit(limit))).all():
                out.append(
                    {
                        "category": cat,
                        "label": r.name,
                        "subtitle": (r.description or "")[:120],
                        "href": href.format(r.id),
                    }
                )
        except Exception:
            logger.exception("search: %s failed", kind)

    # 5. Runs, by id prefix or by what they were asked, your own unless admin
    try:
        from models.agent import Agent
        from models.execution import Execution

        conds = [Execution.input_message.ilike(like)]
        if len(needle) >= 4:
            conds.append(cast(Execution.id, String).ilike(f"{needle}%"))
        stmt = (
            select(
                Execution.id,
                Execution.status,
                Execution.created_at,
                Execution.input_message,
                Agent.name,
            )
            .join(Agent, Agent.id == Execution.agent_id, isouter=True)
            .where(Execution.tenant_id == tenant_id, or_(*conds))
        )
        if not admin:
            stmt = stmt.where(Execution.user_id == user.id)
        rows = (
            await db.execute(stmt.order_by(Execution.created_at.desc()).limit(limit))
        ).all()
        for r in rows:
            status = getattr(r.status, "value", r.status)
            asked = (r.input_message or "").strip().replace("\n", " ")
            # a run whose input is mostly symbols, a pasted log line, is noise here
            if asked and sum(ch.isalnum() for ch in asked[:80]) < len(asked[:80]) * 0.4:
                continue
            out.append(
                {
                    "category": "Runs",
                    "label": f"{r.name or 'Run'}: {asked[:60] or str(r.id)[:8]}",
                    "subtitle": f"{status}, {str(r.id)[:8]}",
                    "href": f"/executions/{r.id}",
                }
            )
    except Exception:
        logger.exception("search: runs failed")

    return success({"results": out, "query": q})
