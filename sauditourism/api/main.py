"""Saudi Tourism Analytics API — standalone tourism intelligence platform."""
from __future__ import annotations

import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "sdk"))

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("sauditourism")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Saudi Tourism API starting on port %s", os.environ.get("PORT", "8002"))
    logger.info("Abenix URL: %s", os.environ.get("ABENIX_API_URL", "http://localhost:8000"))
    has_key = bool(os.environ.get("SAUDITOURISM_ABENIX_API_KEY"))
    logger.info("Abenix SDK key configured: %s", has_key)

    try:
        from app.core.deps import engine
        from app.models.base import Base
        from app.models import tourism_models  # noqa: F401
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Saudi Tourism tables ensured")

        # Seed default test user
        from app.core.deps import SessionLocal
        from app.models.tourism_models import STUser, STUserRole
        from sqlalchemy import select
        import bcrypt
        async with SessionLocal() as db:
            existing = (await db.execute(
                select(STUser).where(STUser.email == "test@sauditourism.gov.sa")
            )).scalar_one_or_none()
            if not existing:
                u = STUser(
                    email="test@sauditourism.gov.sa",
                    password_hash=bcrypt.hashpw(b"TestPass123!", bcrypt.gensalt()).decode(),
                    full_name="Ministry Analyst",
                    organization="Ministry of Tourism",
                    role=STUserRole.ANALYST,
                    is_active=True,
                )
                db.add(u)
                await db.commit()
                logger.info("Seeded default Saudi Tourism test user (test@sauditourism.gov.sa)")
            else:
                logger.info("Saudi Tourism test user already exists")
    except Exception as e:
        logger.exception("Startup bootstrap failed: %s", e)

    try:
        api_key = os.environ.get("SAUDITOURISM_ABENIX_API_KEY", "")
        api_base = os.environ.get("ABENIX_API_URL", "http://localhost:8000")
        if api_key:
            from abenix_sdk import Abenix
            async with Abenix(api_key=api_key, base_url=api_base, timeout=30.0) as forge:
                result = await forge.knowledge.bootstrap_project(
                    slug="sauditourism",
                    name="Saudi Tourism Knowledge",
                    description="Tourism intelligence corpora used by the st-chat agent.",
                    collections=[
                        {
                            "name": "public",
                            "description": "Public reference: visitor stats, attractions, destinations.",
                            "default_visibility": "tenant",
                            "agent_slugs": ["st-chat"],
                            "agent_permission": "READ",
                        },
                        {
                            "name": "operator",
                            "description": "Operator-only datasets: budgets, internal forecasts.",
                            "default_visibility": "private",
                            "agent_slugs": ["st-chat"],
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
            logger.info("Skipping KB v2 bootstrap (SAUDITOURISM_ABENIX_API_KEY not set)")
    except Exception as e:
        # Non-fatal — the rest of the app starts; bootstrap will retry
        # on the next pod restart. This is preferable to crashlooping
        # when Abenix is briefly unavailable during a coordinated
        # deploy.
        logger.warning("KB v2 bootstrap failed (non-fatal): %s", e)

    yield
    logger.info("Saudi Tourism API shutting down")


app = FastAPI(
    title="Saudi Tourism Analytics API",
    description="KSA Ministry of Tourism Intelligence Platform — uses Abenix SDK for AI features",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3002",
        "http://localhost:8002",
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
        "service": "sauditourism-api",
        "version": "1.0.0",
        "abenix_url": os.environ.get("ABENIX_API_URL", "http://localhost:8000"),
        "abenix_sdk_configured": bool(os.environ.get("SAUDITOURISM_ABENIX_API_KEY")),
    }


from app.routers import auth as st_auth
from app.routers import datasets as st_datasets
from app.routers import analytics as st_analytics
from app.routers import simulations as st_simulations
from app.routers import chat as st_chat
from app.routers import reports as st_reports

app.include_router(st_auth.router)
app.include_router(st_datasets.router)
app.include_router(st_analytics.router)
app.include_router(st_simulations.router)
app.include_router(st_chat.router)
app.include_router(st_reports.router)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"data": None, "error": {"message": str(exc), "code": 500}},
    )


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8002"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
