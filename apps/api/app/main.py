from pathlib import Path as _Path
from typing import Any

# Load .env BEFORE any other imports so os.environ has API keys
# In Docker, the directory structure differs — try multiple parent levels
try:
    for _lvl in (3, 2, 1):
        _dotenv_path = _Path(__file__).resolve().parents[_lvl] / ".env"
        if _dotenv_path.exists():
            from dotenv import load_dotenv
            load_dotenv(_dotenv_path, override=False)
            break
except (IndexError, ImportError):
    pass  # No .env in Docker — env vars come from K8s ConfigMap/Secrets

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from sqlalchemy import text

from app.core.config import settings as app_settings
from app.core.logging import setup_logging
from app.core.middleware import BodySizeLimitMiddleware, RateLimitMiddleware, TenantMiddleware
from app.core.observability_middleware import ObservabilityMiddleware
from app.core.telemetry import setup_telemetry
from app.routers import (
    a2a, admin_pricing, admin_scaling, admin_settings, agent_comments, agent_favorites, agent_sharing,
    agents, analytics, api_keys, atlas, auth, batch, billing, bpm_analyzer, code_assets, conversations, creator, executions,
    knowledge, marketplace, mcp, notifications, pipeline_healing, pipelines, reviews,
    settings as settings_router, team, triggers, use_cases, webhook_config, workflow_shell, workspaces,
)

setup_logging(log_level=app_settings.log_level, debug=app_settings.debug)

from app.core.sentry import setup_sentry
setup_sentry()

app = FastAPI(
    title="Abenix API",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    description=(
        "Open-source AI agent platform. Manage agents, pipelines, knowledge "
        "bases, the Atlas ontology canvas, multimodal BPM analysis, "
        "executions, triggers, MCP servers, RBAC, and observability.\n\n"
        "All endpoints are tenant-scoped via JWT or API-key auth; pass an "
        "`X-Abenix-Subject` header to delegate on behalf of an end user "
        "(actAs pattern).\n\n"
        "User guide: see the in-app `/help` page. Source: github.com/your-org/abenix."
    ),
)

setup_telemetry(
    app,
    otel_enabled=app_settings.otel_enabled,
    otel_exporter=app_settings.otel_exporter,
    otel_endpoint=app_settings.otel_endpoint,
)

from app.core.ip_whitelist import IPWhitelistMiddleware
app.add_middleware(IPWhitelistMiddleware)
# NOTE: GZipMiddleware removed — it buffers SSE streams and breaks real-time events.
# SSE responses (text/event-stream) need unbuffered chunk delivery.
app.add_middleware(ObservabilityMiddleware)
app.add_middleware(BodySizeLimitMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(TenantMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=app_settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-Request-ID", "X-API-Key", "X-CIQ-Key"],
    expose_headers=["Retry-After", "X-RateLimit-Remaining", "X-Request-ID"],
    max_age=600,
)

app.include_router(auth.router)
# Register sharing/favorites/comments BEFORE agents router
# so /api/agents/favorites and /api/agents/shared-with-me
# don't get caught by /api/agents/{agent_id}
app.include_router(agent_sharing.router)
app.include_router(agent_comments.router)
app.include_router(agent_favorites.router)
app.include_router(agents.router)
app.include_router(admin_scaling.router)
app.include_router(admin_settings.router)
app.include_router(admin_pricing.router)
app.include_router(use_cases.router)
app.include_router(mcp.router)
app.include_router(knowledge.router)
from app.routers import knowledge_engine, files, knowledge_projects, collection_grants, kb_bootstrap, ontology_schemas, project_members
app.include_router(kb_bootstrap.router)
app.include_router(ontology_schemas.router)
app.include_router(project_members.router)
app.include_router(knowledge_projects.router)
app.include_router(collection_grants.router)
app.include_router(knowledge_engine.router)
app.include_router(files.router)
app.include_router(marketplace.router)
app.include_router(reviews.router)
app.include_router(billing.router)
app.include_router(analytics.router)
app.include_router(settings_router.router)
app.include_router(api_keys.router)
app.include_router(team.router)
app.include_router(creator.router)
app.include_router(notifications.router)
app.include_router(conversations.router)
app.include_router(bpm_analyzer.router)
app.include_router(atlas.router)
app.include_router(pipelines.router)
app.include_router(pipeline_healing.router)
app.include_router(workflow_shell.router)
app.include_router(executions.router)
app.include_router(webhook_config.router)
app.include_router(batch.router)
app.include_router(workspaces.router)
app.include_router(triggers.router)
app.include_router(a2a.router)

from app.routers import memories, tools, ai_builder, tool_library, oraclenet, access_control, sdk_playground, portfolio_schemas, ml_models, load_playground
app.include_router(memories.router)
app.include_router(tools.router)
app.include_router(ai_builder.router)
app.include_router(tool_library.router)
app.include_router(oraclenet.router)
app.include_router(access_control.router)
app.include_router(sdk_playground.router)
app.include_router(portfolio_schemas.router)
app.include_router(ml_models.router)
app.include_router(code_assets.router)
app.include_router(load_playground.router)

from app.routers import account, me as me_router
app.include_router(account.router)
app.include_router(me_router.router)

from app.routers import meetings as meetings_router, persona as persona_router
app.include_router(meetings_router.router)
app.include_router(persona_router.router)

from app.routers import moderation as moderation_router
app.include_router(moderation_router.router)

# the example app has been extracted to /example_app/ as a standalone application.
# It uses the Abenix SDK for AI features via the actAs delegation pattern.


@app.on_event("startup")
async def on_startup():
    """Create any missing database tables from SQLAlchemy models."""
    from app.core.deps import engine as db_engine

    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packages" / "db"))

    from models import Base  # noqa: E402
    async with db_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        # Idempotent column additions for the scaling fields on the
        # agents table. create_all() only adds MISSING columns when it
        # runs against a fresh DB; for upgrades we need explicit ALTERs.
        # All are IF NOT EXISTS so re-runs are safe.
        from sqlalchemy import text as _t
        scaling_ddls = [
            "ALTER TABLE agents ADD COLUMN IF NOT EXISTS runtime_pool VARCHAR(40) NOT NULL DEFAULT 'default'",
            "ALTER TABLE agents ADD COLUMN IF NOT EXISTS min_replicas INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE agents ADD COLUMN IF NOT EXISTS max_replicas INTEGER NOT NULL DEFAULT 10",
            "ALTER TABLE agents ADD COLUMN IF NOT EXISTS concurrency_per_replica INTEGER NOT NULL DEFAULT 3",
            "ALTER TABLE agents ADD COLUMN IF NOT EXISTS rate_limit_qps INTEGER",
            "ALTER TABLE agents ADD COLUMN IF NOT EXISTS daily_budget_usd NUMERIC(10, 2)",
            # platform_settings — admin-only key/value for LLM model
            # selection + other platform-level toggles. Idempotent so
            # re-runs are safe.
            """CREATE TABLE IF NOT EXISTS platform_settings (
                 key VARCHAR(128) PRIMARY KEY,
                 value TEXT NOT NULL DEFAULT '',
                 description TEXT NOT NULL DEFAULT '',
                 category VARCHAR(64) NOT NULL DEFAULT 'general',
                 updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                 updated_by UUID REFERENCES users(id)
               )""",
            "CREATE INDEX IF NOT EXISTS ix_platform_settings_category ON platform_settings (category)",
            # Per-provider cost accounting (commit bad2295). Older DBs
            # have only the single `cost` column; these split it per
            # provider so the billing dashboard can show spend by vendor.
            "ALTER TABLE executions ADD COLUMN IF NOT EXISTS anthropic_cost NUMERIC(10, 6) NOT NULL DEFAULT 0",
            "ALTER TABLE executions ADD COLUMN IF NOT EXISTS openai_cost NUMERIC(10, 6) NOT NULL DEFAULT 0",
            "ALTER TABLE executions ADD COLUMN IF NOT EXISTS google_cost NUMERIC(10, 6) NOT NULL DEFAULT 0",
            "ALTER TABLE executions ADD COLUMN IF NOT EXISTS other_cost NUMERIC(10, 6) NOT NULL DEFAULT 0",
        ]
        for ddl in scaling_ddls:
            try:
                await conn.execute(_t(ddl))
            except Exception as _e:
                import logging
                logging.getLogger("startup").debug("skip ddl %r: %s", ddl, _e)

    # Start APScheduler-based cron trigger scheduler
    from app.core.scheduler import start_scheduler
    start_scheduler()

    # Subscribe to the Redis WS fan-out channel so notifications published
    # on any pod reach the user's WS connection regardless of which API
    # replica accepted the connection. Single-pod dev works unchanged.
    from app.core.ws_manager import ws_manager
    await ws_manager.start()

    try:
        import sys
        from pathlib import Path
        runtime_path = Path("/app/apps/agent-runtime")
        if runtime_path.exists() and str(runtime_path) not in sys.path:
            sys.path.insert(0, str(runtime_path))
        from engine import metrics as _runtime_metrics  # noqa: F401
    except Exception:
        pass


@app.on_event("shutdown")
async def on_shutdown():
    """Stop the scheduler + WS fan-out gracefully."""
    from app.core.scheduler import stop_scheduler
    stop_scheduler()
    from app.core.ws_manager import ws_manager
    await ws_manager.stop()


@app.get("/api/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/health/ready")
async def readiness_check() -> dict[str, Any]:
    from app.core.deps import engine as db_engine

    checks: dict[str, str] = {}

    # PostgreSQL
    try:
        async with db_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception:
        checks["postgres"] = "unavailable"

    # Redis
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(app_settings.redis_url)
        await r.ping()
        await r.aclose()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "unavailable"

    # Neo4j
    try:
        import os
        neo4j_uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
        from neo4j import AsyncGraphDatabase
        driver = AsyncGraphDatabase.driver(
            neo4j_uri,
            auth=(os.environ.get("NEO4J_USER", "neo4j"), os.environ.get("NEO4J_PASSWORD", "abenix")),
        )
        async with driver.session() as session:
            await session.run("RETURN 1")
        await driver.close()
        checks["neo4j"] = "ok"
    except Exception:
        checks["neo4j"] = "unavailable"

    # LLM provider (at least one key configured)
    llm_ok = any([
        app_settings.anthropic_api_key,
        app_settings.openai_api_key,
        app_settings.google_api_key,
    ])
    checks["llm_provider"] = "ok" if llm_ok else "no_key_configured"

    all_ok = all(v == "ok" for v in checks.values())
    return {"status": "ok" if all_ok else "degraded", **checks}


@app.get("/api/metrics")
async def metrics() -> PlainTextResponse:
    """Prometheus scrape endpoint."""
    import os as _os
    multiproc_dir = _os.environ.get("PROMETHEUS_MULTIPROC_DIR", "")
    if multiproc_dir and _os.path.isdir(multiproc_dir):
        try:
            from prometheus_client import CollectorRegistry, multiprocess
            registry = CollectorRegistry()
            multiprocess.MultiProcessCollector(registry)
            return PlainTextResponse(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)
        except Exception:
            pass
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/")
async def root() -> dict[str, Any]:
    return {"data": "Abenix API v0.1.0", "error": None, "meta": {}}
