from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import String, cast, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.responses import success
from models.user import User

router = APIRouter(prefix="/api/search", tags=["search"])


# Static catalogue of in-app routes. Spotlight matches against label + keywords
# and returns href so the client can router.push() straight to the page.
_ROUTES: list[dict[str, Any]] = [
    {
        "label": "Dashboard",
        "href": "/dashboard",
        "keywords": "home overview metrics live",
    },
    {"label": "AI Chat", "href": "/chat", "keywords": "chat conversation ask"},
    {"label": "My Agents", "href": "/agents", "keywords": "agent list bot"},
    {
        "label": "Agent Builder",
        "href": "/builder",
        "keywords": "create new build agent workflow pipeline",
    },
    {"label": "Tools Catalogue", "href": "/tools", "keywords": "tool list catalog"},
    {
        "label": "Code Runner",
        "href": "/code-runner",
        "keywords": "code asset runner execute repo",
    },
    {
        "label": "ML Models",
        "href": "/ml-models",
        "keywords": "ml model train deploy onnx pytorch",
    },
    {
        "label": "Knowledge Bases",
        "href": "/knowledge",
        "keywords": "knowledge document corpus retrieval rag",
    },
    {
        "label": "BPM Analyzer",
        "href": "/bpm-analyzer",
        "keywords": "bpmn process analyzer",
    },
    {"label": "Atlas", "href": "/atlas", "keywords": "atlas graph map knowledge"},
    {
        "label": "Executions",
        "href": "/executions",
        "keywords": "execution run history log activity",
    },
    {
        "label": "Live Debug",
        "href": "/executions/live",
        "keywords": "live debug stream",
    },
    {"label": "Alerts", "href": "/alerts", "keywords": "alert failure error grouped"},
    {
        "label": "Observability Hub",
        "href": "/observability",
        "keywords": "trace tempo grafana telemetry phase observability",
    },
    {
        "label": "Cluster Health",
        "href": "/admin/cluster",
        "keywords": "cluster kubernetes pod memory disk db database health resource",
    },
    {
        "label": "Analytics",
        "href": "/analytics",
        "keywords": "analytics chart cost token usage",
    },
    {
        "label": "Moderation",
        "href": "/moderation",
        "keywords": "moderation safety policy guardrail",
    },
    {
        "label": "Approvals",
        "href": "/approvals",
        "keywords": "approval gate human review hitl",
    },
    {
        "label": "Triggers",
        "href": "/triggers",
        "keywords": "trigger schedule cron webhook",
    },
    {
        "label": "SDK Playground",
        "href": "/sdk-playground",
        "keywords": "sdk playground try",
    },
    {
        "label": "Load Playground",
        "href": "/load-playground",
        "keywords": "load test bench performance",
    },
    {
        "label": "Marketplace",
        "href": "/marketplace",
        "keywords": "marketplace store buy",
    },
    {
        "label": "Settings",
        "href": "/settings",
        "keywords": "settings preference config",
    },
    {
        "label": "API Keys",
        "href": "/settings/api-keys",
        "keywords": "api key token credential",
    },
    {
        "label": "Integrations",
        "href": "/settings/integrations",
        "keywords": "integration connector",
    },
    {"label": "MCP Servers", "href": "/mcp", "keywords": "mcp model context protocol"},
    {
        "label": "Team",
        "href": "/settings/team",
        "keywords": "team member user role rbac",
    },
    {"label": "Help", "href": "/help", "keywords": "help docs walkthrough"},
    {
        "label": "Admin Scaling",
        "href": "/admin/scaling",
        "keywords": "scaling pool keda autoscale",
    },
    {
        "label": "Admin Archives",
        "href": "/admin/archives",
        "keywords": "archive backup rotation",
    },
    {
        "label": "Admin LLM Settings",
        "href": "/admin/llm-settings",
        "keywords": "llm model selection routing",
    },
    {
        "label": "Admin LLM Pricing",
        "href": "/admin/llm-pricing",
        "keywords": "pricing cost token rate",
    },
    {
        "label": "Admin DLQ",
        "href": "/admin/dlq",
        "keywords": "dlq dead letter queue retry",
    },
]


@router.get("")
async def search(
    q: str = Query(..., min_length=1, max_length=80, description="Query string"),
    limit: int = Query(8, ge=1, le=20, description="Max results per category"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Spotlight-style global search across pages, agents, pipelines,
    executions, knowledge bases, ML models, code assets.

    Returns a unified result list with category + label + href so the
    client can navigate straight to the matching surface.
    """
    needle = q.strip().lower()
    out: list[dict[str, Any]] = []

    # 1. Pages — substring on label + keywords
    for row in _ROUTES:
        hay = f"{row['label']} {row.get('keywords', '')}".lower()
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

    # 2. Agents
    try:
        from models.agent import Agent

        like = f"%{needle}%"
        rows = (
            await db.execute(
                select(Agent.id, Agent.name, Agent.description)
                .where(Agent.tenant_id == tenant_id)
                .where(or_(Agent.name.ilike(like), Agent.description.ilike(like)))
                .limit(limit)
            )
        ).all()
        for r in rows:
            out.append(
                {
                    "category": "Agents",
                    "label": r.name,
                    "subtitle": (r.description or "")[:120],
                    "href": f"/agents/{r.id}",
                }
            )
    except Exception:
        pass

    # 3. Pipelines
    try:
        from models.pipeline import Pipeline

        like = f"%{needle}%"
        rows = (
            await db.execute(
                select(Pipeline.id, Pipeline.name, Pipeline.description)
                .where(Pipeline.tenant_id == tenant_id)
                .where(or_(Pipeline.name.ilike(like), Pipeline.description.ilike(like)))
                .limit(limit)
            )
        ).all()
        for r in rows:
            out.append(
                {
                    "category": "Pipelines",
                    "label": r.name,
                    "subtitle": (r.description or "")[:120],
                    "href": f"/builder?pipeline={r.id}",
                }
            )
    except Exception:
        pass

    # 4. Knowledge Bases
    try:
        from models.knowledge import KnowledgeBase

        like = f"%{needle}%"
        rows = (
            await db.execute(
                select(KnowledgeBase.id, KnowledgeBase.name, KnowledgeBase.description)
                .where(KnowledgeBase.tenant_id == tenant_id)
                .where(
                    or_(
                        KnowledgeBase.name.ilike(like),
                        KnowledgeBase.description.ilike(like),
                    )
                )
                .limit(limit)
            )
        ).all()
        for r in rows:
            out.append(
                {
                    "category": "Knowledge",
                    "label": r.name,
                    "subtitle": (r.description or "")[:120],
                    "href": f"/knowledge/{r.id}",
                }
            )
    except Exception:
        pass

    # 5. ML Models
    try:
        from models.ml_model import MLModel

        like = f"%{needle}%"
        rows = (
            await db.execute(
                select(MLModel.id, MLModel.name, MLModel.description)
                .where(MLModel.tenant_id == tenant_id)
                .where(or_(MLModel.name.ilike(like), MLModel.description.ilike(like)))
                .limit(limit)
            )
        ).all()
        for r in rows:
            out.append(
                {
                    "category": "ML Models",
                    "label": r.name,
                    "subtitle": (r.description or "")[:120],
                    "href": f"/ml-models/{r.id}",
                }
            )
    except Exception:
        pass

    # 6. Code Assets
    try:
        from models.code_asset import CodeAsset

        like = f"%{needle}%"
        rows = (
            await db.execute(
                select(CodeAsset.id, CodeAsset.name, CodeAsset.description)
                .where(CodeAsset.tenant_id == tenant_id)
                .where(
                    or_(CodeAsset.name.ilike(like), CodeAsset.description.ilike(like))
                )
                .limit(limit)
            )
        ).all()
        for r in rows:
            out.append(
                {
                    "category": "Code Assets",
                    "label": r.name,
                    "subtitle": (r.description or "")[:120],
                    "href": f"/code-runner?asset={r.id}",
                }
            )
    except Exception:
        pass

    # 7. Recent executions — only match against id prefix (so users can paste a trace_id)
    if len(needle) >= 8:
        try:
            from models.execution import Execution

            like_id = f"{needle}%"
            rows = (
                await db.execute(
                    select(Execution.id, Execution.status, Execution.created_at)
                    .where(Execution.tenant_id == tenant_id)
                    .where(cast(Execution.id, String).ilike(like_id))
                    .order_by(Execution.created_at.desc())
                    .limit(limit)
                )
            ).all()
            for r in rows:
                out.append(
                    {
                        "category": "Executions",
                        "label": str(r.id)[:8] + "...",
                        "subtitle": f"status={r.status}",
                        "href": f"/executions/{r.id}",
                    }
                )
        except Exception:
            pass

    return success({"results": out, "query": q})
