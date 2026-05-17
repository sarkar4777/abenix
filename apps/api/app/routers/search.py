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
    # PINNED
    {"label": "Dashboard", "href": "/dashboard", "keywords": "home overview metrics live pinned"},
    {"label": "My Agents", "href": "/agents", "keywords": "agent list bot pinned"},
    {"label": "AI Chat", "href": "/chat", "keywords": "chat conversation ask pinned"},
    {"label": "Alerts", "href": "/alerts", "keywords": "alert failure error grouped pinned"},
    # BUILD
    {"label": "Agent Builder", "href": "/builder", "keywords": "create new build agent workflow pipeline canvas"},
    {"label": "Tools Catalogue", "href": "/tools", "keywords": "tool list catalog build"},
    {"label": "Code Runner", "href": "/code-runner", "keywords": "code asset runner execute repo build go python java"},
    {"label": "ML Models", "href": "/ml-models", "keywords": "ml model train deploy onnx pytorch build"},
    {"label": "Knowledge Bases", "href": "/knowledge", "keywords": "knowledge document corpus retrieval rag build"},
    {"label": "Persona KB", "href": "/persona", "keywords": "persona profile build"},
    {"label": "Portfolio Schemas", "href": "/portfolio-schemas", "keywords": "schema json output build"},
    {"label": "BPM Analyzer", "href": "/bpm-analyzer", "keywords": "bpmn process analyzer build"},
    {"label": "Atlas", "href": "/atlas", "keywords": "atlas graph map knowledge build"},
    # RUN & TEST
    {"label": "SDK Playground", "href": "/sdk-playground", "keywords": "sdk playground try test"},
    {"label": "Load Playground", "href": "/load-playground", "keywords": "load test bench performance run"},
    {"label": "Triggers", "href": "/triggers", "keywords": "trigger schedule cron webhook run"},
    # MONITOR
    {"label": "Observability Hub", "href": "/observability", "keywords": "trace tempo grafana telemetry phase monitor observability"},
    {"label": "Executions", "href": "/executions", "keywords": "execution run history log activity monitor"},
    {"label": "Live Debug", "href": "/executions/live", "keywords": "live debug stream monitor"},
    {"label": "Analytics", "href": "/analytics", "keywords": "analytics chart cost token usage monitor"},
    {"label": "Moderation", "href": "/moderation", "keywords": "moderation safety policy guardrail monitor"},
    # MONETIZE
    {"label": "Marketplace", "href": "/marketplace", "keywords": "marketplace store buy"},
    {"label": "Creator Hub", "href": "/creator", "keywords": "creator earnings revenue payouts"},
    # ADMIN
    {"label": "Cluster Health", "href": "/admin/cluster", "keywords": "cluster kubernetes pod memory disk db database health resource admin"},
    {"label": "Scaling", "href": "/admin/scaling", "keywords": "scaling pool keda autoscale admin"},
    {"label": "Archives", "href": "/admin/archives", "keywords": "archive backup rotation admin"},
    {"label": "Model Selection", "href": "/admin/llm-settings", "keywords": "llm model selection routing admin"},
    {"label": "LLM Pricing", "href": "/admin/llm-pricing", "keywords": "pricing cost token rate admin"},
    {"label": "Connectors", "href": "/admin/connectors", "keywords": "connector admin"},
    {"label": "Dead Letter Queue", "href": "/admin/dlq", "keywords": "dlq dead letter queue retry admin"},
    {"label": "Review Queue", "href": "/review-queue", "keywords": "review queue approval admin"},
    {"label": "Team", "href": "/settings/team", "keywords": "team member user role rbac admin"},
    # WORKSPACE
    {"label": "Approvals", "href": "/approvals", "keywords": "approval gate human review hitl workspace"},
    {"label": "MCP Servers", "href": "/mcp", "keywords": "mcp model context protocol workspace"},
    {"label": "Edge", "href": "/edge", "keywords": "edge runtime workspace"},
    {"label": "API Keys", "href": "/settings/api-keys", "keywords": "api key token credential workspace"},
    {"label": "Integrations", "href": "/settings/integrations", "keywords": "integration connector workspace"},
    {"label": "Settings", "href": "/settings", "keywords": "settings preference config workspace"},
    {"label": "Settings — Profile", "href": "/settings/profile", "keywords": "profile avatar name workspace"},
    {"label": "Settings — Security", "href": "/settings/security", "keywords": "security 2fa password workspace"},
    {"label": "Settings — Billing", "href": "/settings/billing", "keywords": "billing plan subscription payment workspace"},
    {"label": "Settings — Notifications", "href": "/settings/notifications", "keywords": "notification email slack alert workspace"},
    {"label": "Settings — Quotas", "href": "/settings/quotas", "keywords": "quota limit rate workspace"},
    {"label": "Settings — Webhooks", "href": "/settings/webhooks", "keywords": "webhook callback workspace"},
    {"label": "Settings — Observability", "href": "/settings/observability", "keywords": "settings observability workspace"},
    {"label": "Settings — Sandbox", "href": "/settings/sandbox", "keywords": "sandbox settings workspace"},
    {"label": "Settings — Privacy", "href": "/settings/privacy", "keywords": "privacy gdpr workspace"},
    {"label": "Settings — Data", "href": "/settings/data", "keywords": "data export retention workspace"},
    {"label": "Help", "href": "/help", "keywords": "help docs walkthrough workspace"},
    {"label": "Meetings", "href": "/meetings", "keywords": "meeting calendar workspace"},
    # Other top-level
    {"label": "Webhooks", "href": "/webhooks", "keywords": "webhook list workspace"},
    {"label": "OracleNet", "href": "/oraclenet", "keywords": "oraclenet research synthesis"},
    {"label": "Docs", "href": "/docs", "keywords": "documentation api reference"},
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
            out.append({
                "category": "Pages",
                "label": row["label"],
                "subtitle": row["href"],
                "href": row["href"],
            })
            if sum(1 for x in out if x["category"] == "Pages") >= limit:
                break

    tenant_id = user.tenant_id

    # 2. Agents
    try:
        from models.agent import Agent
        like = f"%{needle}%"
        rows = (await db.execute(
            select(Agent.id, Agent.name, Agent.description)
            .where(Agent.tenant_id == tenant_id)
            .where(or_(Agent.name.ilike(like), Agent.description.ilike(like)))
            .limit(limit)
        )).all()
        for r in rows:
            out.append({
                "category": "Agents",
                "label": r.name,
                "subtitle": (r.description or "")[:120],
                "href": f"/agents/{r.id}",
            })
    except Exception:
        pass

    # 3. Pipelines
    try:
        from models.pipeline import Pipeline
        like = f"%{needle}%"
        rows = (await db.execute(
            select(Pipeline.id, Pipeline.name, Pipeline.description)
            .where(Pipeline.tenant_id == tenant_id)
            .where(or_(Pipeline.name.ilike(like), Pipeline.description.ilike(like)))
            .limit(limit)
        )).all()
        for r in rows:
            out.append({
                "category": "Pipelines",
                "label": r.name,
                "subtitle": (r.description or "")[:120],
                "href": f"/builder?pipeline={r.id}",
            })
    except Exception:
        pass

    # 4. Knowledge Bases
    try:
        from models.knowledge import KnowledgeBase
        like = f"%{needle}%"
        rows = (await db.execute(
            select(KnowledgeBase.id, KnowledgeBase.name, KnowledgeBase.description)
            .where(KnowledgeBase.tenant_id == tenant_id)
            .where(or_(KnowledgeBase.name.ilike(like), KnowledgeBase.description.ilike(like)))
            .limit(limit)
        )).all()
        for r in rows:
            out.append({
                "category": "Knowledge",
                "label": r.name,
                "subtitle": (r.description or "")[:120],
                "href": f"/knowledge/{r.id}",
            })
    except Exception:
        pass

    # 5. ML Models
    try:
        from models.ml_model import MLModel
        like = f"%{needle}%"
        rows = (await db.execute(
            select(MLModel.id, MLModel.name, MLModel.description)
            .where(MLModel.tenant_id == tenant_id)
            .where(or_(MLModel.name.ilike(like), MLModel.description.ilike(like)))
            .limit(limit)
        )).all()
        for r in rows:
            out.append({
                "category": "ML Models",
                "label": r.name,
                "subtitle": (r.description or "")[:120],
                "href": f"/ml-models/{r.id}",
            })
    except Exception:
        pass

    # 6. Code Assets
    try:
        from models.code_asset import CodeAsset
        like = f"%{needle}%"
        rows = (await db.execute(
            select(CodeAsset.id, CodeAsset.name, CodeAsset.description)
            .where(CodeAsset.tenant_id == tenant_id)
            .where(or_(CodeAsset.name.ilike(like), CodeAsset.description.ilike(like)))
            .limit(limit)
        )).all()
        for r in rows:
            out.append({
                "category": "Code Assets",
                "label": r.name,
                "subtitle": (r.description or "")[:120],
                "href": f"/code-runner?asset={r.id}",
            })
    except Exception:
        pass

    # 7. Recent executions — only match against id prefix (so users can paste a trace_id)
    if len(needle) >= 8:
        try:
            from models.execution import Execution
            like_id = f"{needle}%"
            rows = (await db.execute(
                select(Execution.id, Execution.status, Execution.created_at)
                .where(Execution.tenant_id == tenant_id)
                .where(cast(Execution.id, String).ilike(like_id))
                .order_by(Execution.created_at.desc())
                .limit(limit)
            )).all()
            for r in rows:
                out.append({
                    "category": "Executions",
                    "label": str(r.id)[:8] + "...",
                    "subtitle": f"status={r.status}",
                    "href": f"/executions/{r.id}",
                })
        except Exception:
            pass

    return success({"results": out, "query": q})
