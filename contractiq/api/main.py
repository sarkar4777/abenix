"""ContractIQ API — standalone PPA & Gas Contract Intelligence platform."""

from __future__ import annotations

import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# Add the SDK directory and the current dir to sys.path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "sdk"))

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("contractiq")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("ContractIQ API starting on port %s", os.environ.get("PORT", "8001"))
    logger.info("Abenix URL: %s", os.environ.get("ABENIX_API_URL", "http://localhost:8000"))
    has_key = bool(os.environ.get("CONTRACTIQ_ABENIX_API_KEY"))
    logger.info("Abenix SDK key configured: %s", has_key)

    # Auto-create tables and seed test user on startup
    try:
        from app.core.deps import engine
        from app.models.base import Base
        from app.models import contractiq_models  # noqa: F401 — register models
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            # Light-touch ALTERs for columns that widened since initial create.
            # Idempotent — Postgres ALTER TYPE VARCHAR(n) is a no-op if already wider.
            from sqlalchemy import text as _t
            for ddl in [
                "ALTER TABLE contractiq_credit_risks ALTER COLUMN risk_level TYPE VARCHAR(40)",
                "ALTER TABLE contractiq_credit_risks ALTER COLUMN z_score_zone TYPE VARCHAR(40)",
                "ALTER TABLE contractiq_credit_risks ALTER COLUMN credit_rating TYPE VARCHAR(80)",
                "ALTER TABLE contractiq_credit_risks ALTER COLUMN sector TYPE VARCHAR(255)",
                "ALTER TABLE contractiq_credit_risks ALTER COLUMN ticker TYPE VARCHAR(40)",
                "ALTER TYPE contract_type ADD VALUE IF NOT EXISTS 'metals'",
                "ALTER TABLE contractiq_contracts ADD COLUMN IF NOT EXISTS asset_class VARCHAR(40)",
                "ALTER TABLE contractiq_contracts ADD COLUMN IF NOT EXISTS pricing_pattern VARCHAR(40)",
                "ALTER TABLE contractiq_contracts ADD COLUMN IF NOT EXISTS quantity JSONB",
            ]:
                try:
                    await conn.execute(_t(ddl))
                except Exception as _e:
                    logger.debug("skip ddl %r: %s", ddl, _e)
        logger.info("ContractIQ tables ensured")

        # Seed default test user if missing
        from app.core.deps import SessionLocal
        from app.models.contractiq_models import ContractIQUser, ContractIQUserRole
        from sqlalchemy import select
        import bcrypt
        async with SessionLocal() as db:
            existing = (await db.execute(
                select(ContractIQUser).where(ContractIQUser.email == "test@contractiq.com")
            )).scalar_one_or_none()
            if not existing:
                u = ContractIQUser(
                    email="test@contractiq.com",
                    password_hash=bcrypt.hashpw(b"TestPass123!", bcrypt.gensalt()).decode(),
                    full_name="Test User",
                    organization="ContractIQ Demo",
                    role=ContractIQUserRole.ANALYST,
                    is_active=True,
                )
                db.add(u)
                await db.commit()
                logger.info("Seeded default ContractIQ test user (test@contractiq.com)")
            else:
                logger.info("ContractIQ test user already exists")
    except Exception as e:
        logger.exception("Startup bootstrap failed: %s", e)

    try:
        from app.core.quickwin_seed import seed_quickwin_data
        async with SessionLocal() as db:
            summary = await seed_quickwin_data(db)
            logger.info(
                "QuickWin seed: counterparties=%s statements=%s ratios=%s permits=%s alerts=%s",
                summary.get("counterparties"),
                summary.get("statements"),
                summary.get("ratios"),
                summary.get("permits"),
                summary.get("alerts"),
            )
    except Exception as e:
        logger.warning("QuickWin seed failed (non-fatal): %s", e)

    try:
        api_key = os.environ.get("CONTRACTIQ_ABENIX_API_KEY", "")
        api_base = os.environ.get("ABENIX_API_URL", "http://localhost:8000")
        if api_key:
            from abenix_sdk import Abenix
            async with Abenix(api_key=api_key, base_url=api_base, timeout=30.0) as forge:
                result = await forge.knowledge.bootstrap_project(
                    slug="contractiq",
                    name="ContractIQ Knowledge",
                    description="Contract corpora — per-user collections auto-created on first cognify.",
                    collections=[
                        {
                            "name": "contractiq-shared",
                            "description": "Shared reference corpus (clause library, benchmarks).",
                            "default_visibility": "tenant",
                            "agent_slugs": [
                                "contractiq-chat", "contractiq-extractor",
                                "contractiq-clause-benchmarker", "contractiq-portfolio-valuator",
                            ],
                            "agent_permission": "READ",
                        },
                    ],
                )
                logger.info(
                    "KB v2 bootstrap done: project=%s collections=%s skipped_agents=%s",
                    result.get("project", {}).get("slug"),
                    [c["name"] for c in result.get("collections", [])],
                    result.get("skipped_agents") or [],
                )
        else:
            logger.info("Skipping KB v2 bootstrap (CONTRACTIQ_ABENIX_API_KEY not set)")
    except Exception as e:
        logger.warning("KB v2 bootstrap failed (non-fatal): %s", e)

    try:
        from app.core.deps import SessionLocal
        from app.core.quickwin_seed import seed_quickwin_data
        async with SessionLocal() as db:
            summary = await seed_quickwin_data(db)
            logger.info("Quickwin seed: %s", summary)
    except Exception as e:
        logger.warning("Quickwin seed failed (non-fatal): %s", e)

    # ── Reconcile stuck extractions (pod-restart / torn SSE recovery) ──
    reconciler_task = None
    try:
        from app.core.reconciler import reconcile_stuck_extractions_once, reconciler_loop
        import asyncio as _asyncio
        await reconcile_stuck_extractions_once()
        reconciler_task = _asyncio.create_task(reconciler_loop())
        logger.info("Reconciler loop started (5-min cadence)")
    except Exception as e:
        logger.exception("Failed to start reconciler: %s", e)

    yield

    if reconciler_task is not None:
        reconciler_task.cancel()
        try:
            await reconciler_task
        except Exception:
            pass
    logger.info("ContractIQ API shutting down")


app = FastAPI(
    title="ContractIQ API",
    description="PPA & Gas Contract Intelligence Platform — uses Abenix SDK for AI features",
    version="1.0.0",
    lifespan=lifespan,
)

try:
    from abenix_sdk.tracing import init_tracing as _init_tracing
    _init_tracing("contractiq-api", fastapi_app=app)
except Exception:
    pass

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:8001",
        "*",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "service": "contractiq-api",
        "version": "1.0.0",
        "abenix_url": os.environ.get("ABENIX_API_URL", "http://localhost:8000"),
        "abenix_sdk_configured": bool(os.environ.get("CONTRACTIQ_ABENIX_API_KEY")),
    }


from app.routers import auth as ciq_auth
from app.routers import contracts as ciq_contracts
from app.routers import analysis as ciq_analysis
from app.routers import insights as ciq_insights
from app.routers import templates as ciq_templates
from app.routers import metals as ciq_metals
from app.routers import market as ciq_market
from app.routers import risk as ciq_risk
from app.routers import whatif as ciq_whatif
from app.routers import rbac as ciq_rbac
from app.routers import rules as ciq_rules
from app.routers import audit as ciq_audit
from app.routers import executions as ciq_executions
from app.routers import quickwin as ciq_quickwin

app.include_router(ciq_auth.router)
app.include_router(ciq_contracts.router)
app.include_router(ciq_analysis.router)
app.include_router(ciq_insights.router)
app.include_router(ciq_templates.router)
app.include_router(ciq_metals.router)
app.include_router(ciq_market.router)
app.include_router(ciq_risk.router)
app.include_router(ciq_whatif.router)
app.include_router(ciq_rbac.router)
app.include_router(ciq_rules.router)
app.include_router(ciq_audit.router)
app.include_router(ciq_executions.router)
app.include_router(ciq_quickwin.router)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"data": None, "error": {"message": str(exc), "code": 500}},
    )


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8001"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
