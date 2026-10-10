import logging
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

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from sqlalchemy import text

from app.core.config import settings as app_settings
from app.core.logging import setup_logging
from app.core.middleware import (  # noqa: F401
    SecurityHeadersMiddleware,
)
from app.core.middleware import (
    BodySizeLimitMiddleware,
    RateLimitMiddleware,
    TenantMiddleware,
)
from app.core.observability_middleware import ObservabilityMiddleware
from app.core.telemetry import setup_telemetry
from app.routers import (
    a2a,
    admin_pricing,
    admin_scaling,
    admin_model_availability,
    llm_models,
    admin_settings,
    admin_tool_config,
    governance,
    decisions,
    public_settings,
    platform_features,
    agent_comments,
    agent_favorites,
    agent_sharing,
    agents,
    analytics,
    api_keys,
    atlas,
    auth,
    batch,
    billing,
    bpm_analyzer,
    code_assets,
    conversations,
    creator,
    edge,
    executions,
    knowledge,
    marketplace,
    mcp,
    notifications,
    pipeline_healing,
    pipelines,
    reviews,
    settings as settings_router,
    team,
    triggers,
    use_cases,
    webhook_config,
    workflow_shell,
    workspaces,
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


def _custom_openapi() -> dict:
    if app.openapi_schema:
        return app.openapi_schema
    from fastapi.openapi.utils import get_openapi

    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    schema.setdefault("components", {}).setdefault("securitySchemes", {})
    schema["components"]["securitySchemes"]["BearerAuth"] = {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
    }
    schema["components"]["securitySchemes"]["ApiKeyAuth"] = {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Key",
    }
    schema["security"] = [{"BearerAuth": []}, {"ApiKeyAuth": []}]
    app.openapi_schema = schema
    return schema


app.openapi = _custom_openapi

from app.core.ip_whitelist import IPWhitelistMiddleware

# Inner middlewares first. In FastAPI/Starlette `add_middleware` uses
# insert(0,...), so the LAST registered middleware is the OUTERMOST
# wrapper. We register CORS dead last so it wraps every other middleware
# and every exception handler — that way 401/403/429/5xx responses still
# carry Access-Control-Allow-Origin and the browser shows the real status
# instead of a misleading "CORS policy" error.
app.add_middleware(SecurityHeadersMiddleware)
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
    allow_headers=[
        "Authorization",
        "Content-Type",
        "Accept",
        "X-Request-ID",
        "X-API-Key",
        "X-CIQ-Key",
        "X-Abenix-Subject",
        "If-Match",
        "If-None-Match",
    ],
    expose_headers=[
        "Retry-After",
        "X-RateLimit-Remaining",
        "X-Request-ID",
        "ETag",
        # file downloads keep their real name
        "Content-Disposition",
    ],
    max_age=600,
)


def _cors_headers_for(request: Request) -> dict[str, str]:
    """Return the CORS headers that CORSMiddleware would add for this origin.

    Used by exception handlers below — without this, a 401 raised inside a
    route dependency can short-circuit past CORSMiddleware on some Starlette
    versions, and the browser then reports the real error as a CORS failure.
    """
    origin = request.headers.get("origin")
    if not origin:
        return {}
    allowed = app_settings.cors_origins
    if "*" in allowed or origin in allowed:
        return {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Credentials": "true",
            "Vary": "Origin",
        }
    return {}


@app.exception_handler(HTTPException)
async def _http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail
    message = detail if isinstance(detail, str) else "Request failed"
    payload: dict[str, Any] = {"message": message, "code": exc.status_code}
    if isinstance(detail, dict):
        if "error_code" in detail:
            payload["error_code"] = detail.get("error_code")
        if "details" in detail:
            payload["details"] = detail.get("details")
        if "message" in detail:
            payload["message"] = detail.get("message")
    return JSONResponse(
        status_code=exc.status_code,
        content={"data": None, "error": payload},
        headers={**(exc.headers or {}), **_cors_headers_for(request)},
    )


from sqlalchemy.exc import TimeoutError as _PoolTimeout  # noqa: E402


@app.exception_handler(_PoolTimeout)
async def _pool_timeout_handler(request: Request, exc: _PoolTimeout) -> JSONResponse:
    # every connection is in use, a retry soon will usually get one
    return JSONResponse(
        status_code=503,
        content={
            "data": None,
            "error": {
                "message": "The service is busy, retry shortly.",
                "code": 503,
                "error_code": "BUSY",
            },
        },
        headers={"Retry-After": "2", **_cors_headers_for(request)},
    )


@app.exception_handler(RequestValidationError)
async def _validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "data": None,
            "error": {
                "message": "Request validation failed",
                "code": 422,
                "error_code": "VALIDATION_ERROR",
                "details": {"errors": exc.errors()},
            },
        },
        headers=_cors_headers_for(request),
    )


app.include_router(auth.router)
from app.routers import sso as _sso_router

app.include_router(_sso_router.router)
from app.routers import sso_oidc as _sso_oidc_router
from app.routers import two_factor as _two_factor_router

app.include_router(_sso_oidc_router.router)
app.include_router(_two_factor_router.router)
from app.routers import (
    document_grants as _doc_grants_mod,
    knowledge_v2 as _kb_v2_mod,
    gdpr as _gdpr_mod,
)

app.include_router(_doc_grants_mod.router)
app.include_router(_kb_v2_mod.router)
app.include_router(_gdpr_mod.router)
app.include_router(agent_sharing.router)
app.include_router(agent_comments.router)
app.include_router(agent_favorites.router)
app.include_router(agents.router)
from app.routers import invocations as _invocations_mod, archives as _archives_mod

app.include_router(_invocations_mod.router)
app.include_router(_archives_mod.router)
from app.routers import evals as _evals_mod

app.include_router(_evals_mod.router)
app.include_router(admin_scaling.router)
app.include_router(admin_settings.router)
app.include_router(admin_tool_config.router)
app.include_router(governance.router)
app.include_router(decisions.router)
app.include_router(decisions.refs_router)
app.include_router(public_settings.router)
app.include_router(platform_features.router)
app.include_router(admin_pricing.router)
app.include_router(admin_model_availability.router)
app.include_router(llm_models.router)
app.include_router(llm_models.provider_router)
app.include_router(use_cases.router)
app.include_router(mcp.router)
app.include_router(knowledge.router)
from app.routers import (
    knowledge_engine,
    files,
    knowledge_projects,
    collection_grants,
    kb_bootstrap,
    ontology_schemas,
    project_members,
)

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
app.include_router(edge.router)
app.include_router(webhook_config.router)
app.include_router(batch.router)
app.include_router(workspaces.router)
app.include_router(triggers.router)
app.include_router(a2a.router)

from app.routers import (
    memories,
    tools,
    integrations,
    ai_builder,
    tool_library,
    oraclenet,
    access_control,
    sdk_playground,
    portfolio_schemas,
    ml_models,
    load_playground,
)

app.include_router(memories.router)
app.include_router(tools.router)

from app.routers import tool_presets as _tool_presets_mod
from app.routers import tool_runtime as _tool_runtime_mod

app.include_router(_tool_presets_mod.router)
app.include_router(_tool_runtime_mod.router)
app.include_router(integrations.router)
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

from app.routers import (
    connectors as connectors_router,
    approvals as approvals_router,
    admin_dlq as admin_dlq_router,
    admin_jobs as admin_jobs_router,
)

app.include_router(connectors_router.router)
app.include_router(approvals_router.router)
app.include_router(admin_dlq_router.router)
app.include_router(admin_jobs_router.router)

from app.routers import search as search_router, admin_cluster as admin_cluster_router
from app.routers import admin_alerts as admin_alerts_router

app.include_router(search_router.router)
app.include_router(admin_cluster_router.router)
app.include_router(admin_alerts_router.router)

from app.routers import sources as sources_router

app.include_router(sources_router.router)

from app.routers import autonomy as autonomy_router

app.include_router(autonomy_router.router)

from app.routers import lessons as lessons_router

app.include_router(lessons_router.router)

from app.routers import improvements_proposals as improvements_proposals_router

app.include_router(improvements_proposals_router.router)

from app.routers import journey as journey_router

app.include_router(journey_router.router)

from app.routers import inbox as inbox_router

app.include_router(inbox_router.router)

# ContractIQ has been extracted to /contractiq/ as a standalone application.
# It uses the Abenix SDK for AI features via the actAs delegation pattern.


@app.on_event("startup")
async def on_startup():
    """Create any missing database tables from SQLAlchemy models."""
    from app.core.deps import engine as db_engine
    from app.core.secret_storage import check_at_startup

    check_at_startup()
    from app.core import capabilities as _caps

    _caps.start_listener()

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
            "ALTER TABLE executions ADD COLUMN IF NOT EXISTS trace_id VARCHAR(32)",
            "CREATE INDEX IF NOT EXISTS ix_executions_trace_id ON executions (trace_id) WHERE trace_id IS NOT NULL",
        ]
        import logging as _logging

        _slog = _logging.getLogger("startup")

        # ADD COLUMN IF NOT EXISTS still takes an ACCESS EXCLUSIVE lock, so one
        # pod does the work and settled columns are skipped — else rollouts hang.
        got_lock = bool(
            (await conn.execute(_t("SELECT pg_try_advisory_lock(776601)"))).scalar()
        )
        if not got_lock:
            _slog.info("startup ddl: another pod holds the lock — skipping")
        else:
            try:
                existing = {
                    (r[0], r[1])
                    for r in (
                        await conn.execute(
                            _t(
                                "SELECT table_name, column_name FROM "
                                "information_schema.columns WHERE table_schema "
                                "= current_schema()"
                            )
                        )
                    ).all()
                }

                import re as _re

                _add_col = _re.compile(
                    r"ALTER TABLE (\w+) ADD COLUMN IF NOT EXISTS (\w+)", _re.I
                )
                applied = skipped = 0
                for ddl in scaling_ddls:
                    m = _add_col.match(ddl.strip())
                    if m and (m.group(1), m.group(2)) in existing:
                        skipped += 1
                        continue
                    try:
                        await conn.execute(_t(ddl))
                        applied += 1
                    except Exception as _e:
                        _slog.debug("skip ddl %r: %s", ddl, _e)
                _slog.info(
                    "startup ddl: %d applied, %d already present", applied, skipped
                )
            finally:
                await conn.execute(_t("SELECT pg_advisory_unlock(776601)"))

    # The pgvector chunk store. It lives here and not in create_all because
    # `chunks` is raw SQL outside the ORM, and not in its alembic revision
    # because that revision sits on a head the database never reached — so the
    # table simply never existed, every ingest ended "vector store
    # unavailable", and knowledge_search had nothing to search. Its own
    # transaction: a CREATE EXTENSION the role is not allowed to run would
    # otherwise abort the one that just built the schema.
    try:
        from sqlalchemy import text as _vt

        async with db_engine.begin() as vconn:
            await vconn.execute(_vt("CREATE EXTENSION IF NOT EXISTS vector"))
            await vconn.execute(
                _vt(
                    """
                    CREATE TABLE IF NOT EXISTS chunks (
                        id UUID PRIMARY KEY,
                        collection_id UUID NOT NULL
                            REFERENCES knowledge_collections(id) ON DELETE CASCADE,
                        document_id UUID NOT NULL
                            REFERENCES documents(id) ON DELETE CASCADE,
                        chunk_index INTEGER NOT NULL,
                        content TEXT NOT NULL,
                        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                        embedding vector(1536),
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        UNIQUE (document_id, chunk_index)
                    )
                    """
                )
            )
            await vconn.execute(
                _vt(
                    "CREATE INDEX IF NOT EXISTS ix_chunks_collection "
                    "ON chunks (collection_id)"
                )
            )
            await vconn.execute(
                _vt(
                    "CREATE INDEX IF NOT EXISTS ix_chunks_document "
                    "ON chunks (document_id)"
                )
            )
        # HNSW wants pgvector 0.5+. Separate transaction so an older build
        # loses the speed-up and keeps the table.
        try:
            async with db_engine.begin() as iconn:
                await iconn.execute(
                    _vt(
                        "CREATE INDEX IF NOT EXISTS ix_chunks_embedding_hnsw "
                        "ON chunks USING hnsw (embedding vector_cosine_ops)"
                    )
                )
        except Exception as _e:
            logging.getLogger("startup").info("chunks hnsw index skipped: %s", _e)
    except Exception as _e:
        logging.getLogger("startup").warning(
            "pgvector chunk store unavailable (%s) — knowledge search will "
            "report 'vector store unavailable' until the database role can "
            "CREATE EXTENSION vector",
            _e,
        )

    # Seed system tool presets for every tenant. Idempotent; preserves
    # user edits to existing rows (only flips is_system back on).
    try:
        from app.core.deps import async_session
        from app.core.seed_tool_presets import seed_presets_for_all_tenants

        async with async_session() as _seed_db:
            await seed_presets_for_all_tenants(_seed_db)
    except Exception as _e:
        logging.getLogger("startup").warning("seed tool presets skipped: %s", _e)

    # Seed per-tool runtime defaults (cache / semaphore / rate-limit).
    # Idempotent: only inserts missing slugs.
    try:
        from app.core.deps import async_session
        from app.core.seed_tool_runtime import seed_tool_runtime_defaults

        async with async_session() as _seed_db:
            await seed_tool_runtime_defaults(_seed_db)
    except Exception as _e:
        logging.getLogger("startup").warning(
            "seed tool_runtime defaults skipped: %s", _e
        )

    # Start APScheduler-based cron trigger scheduler
    from app.core.scheduler import start_scheduler

    start_scheduler()

    try:
        import sys as _sys
        from pathlib import Path as _Path

        _rp = _Path("/app/apps/agent-runtime")
        if _rp.exists() and str(_rp) not in _sys.path:
            _sys.path.insert(0, str(_rp))
        from engine.tracing import init_tracing as _init_tracing

        _init_tracing("abenix-api")
        try:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

            FastAPIInstrumentor.instrument_app(app)
        except Exception as _e:
            logging.getLogger("startup").debug(
                "fastapi auto-instrument skipped: %s", _e
            )
        try:
            from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

            HTTPXClientInstrumentor().instrument()
        except Exception:
            pass
    except Exception as _e:
        logging.getLogger("startup").info("tracing init skipped: %s", _e)

    # Subscribe to the Redis WS fan-out channel so notifications published
    # on any pod reach the user's WS connection regardless of which API
    # replica accepted the connection. Single-pod dev works unchanged.
    from app.core.ws_manager import ws_manager

    await ws_manager.start()

    from app.core import dependency_health

    dependency_health.start()

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

    from app.core import dependency_health

    await dependency_health.stop()


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
            auth=(
                os.environ.get("NEO4J_USER", "neo4j"),
                os.environ.get("NEO4J_PASSWORD", "abenix"),
            ),
        )
        async with driver.session() as session:
            await session.run("RETURN 1")
        await driver.close()
        checks["neo4j"] = "ok"
    except Exception:
        checks["neo4j"] = "unavailable"

    # LLM provider (at least one key configured)
    llm_ok = any(
        [
            app_settings.anthropic_api_key,
            app_settings.openai_api_key,
            app_settings.google_api_key,
        ]
    )
    checks["llm_provider"] = "ok" if llm_ok else "no_key_configured"

    from app.core import dependency_health

    dependency_health.record("postgres", checks["postgres"] == "ok")
    dependency_health.record("redis", checks["redis"] == "ok")

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
            return PlainTextResponse(
                generate_latest(registry), media_type=CONTENT_TYPE_LATEST
            )
        except Exception:
            pass
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/")
async def root() -> dict[str, Any]:
    return {"data": "Abenix API v0.1.0", "error": None, "meta": {}}
