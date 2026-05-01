"""ResolveAI API — customer service agent platform.

Thin FastAPI app that owns its own case-lifecycle tables and uses the
bundled ``abenix_sdk`` for every reasoning step. No Abenix
code is imported at runtime.

Phase-2 persistence: when ``DATABASE_URL`` is set, all writes land in
Postgres via SQLAlchemy (see ``app/core/db.py`` + ``app/core/store.py``).
When it's not set, we fall back to the in-process dict store — same
public interface, zero dependencies, perfect for local demos.

Run locally:
    cd resolveai/api
    python main.py              # PORT defaults to 8004

Environment:
    ABENIX_API_URL               e.g. http://localhost:8000 (or cluster DNS)
    RESOLVEAI_ABENIX_API_KEY     af_xxxxx
    DATABASE_URL                     optional — postgresql+asyncpg://…

Design of record: ``docs/RESOLVEAI_DESIGN.md``.
"""
from __future__ import annotations

import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "sdk"))

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from app.core.db import db_enabled, init_tables  # noqa: E402
from app.core.store import build_store  # noqa: E402
from app.routers import admin as admin_router  # noqa: E402
from app.routers import cases as cases_router  # noqa: E402
from app.routers import qa as qa_router  # noqa: E402
from app.routers import sla as sla_router  # noqa: E402
from app.routers import trends as trends_router  # noqa: E402
from app.routers._deps import get_store, get_tenant_id, _maybe  # noqa: E402


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("resolveai")


# ─── Pipeline catalogue ────────────────────────────────────────────────
# Matches the seed slugs in resolveai/seeds/agents/*.yaml.
PIPELINES: dict[str, dict[str, Any]] = {
    "inbound-resolution": {
        "slug": "resolveai-inbound-resolution",
        "label": "Inbound Resolution",
        "description": "Triage → Context → Policy Research → Plan → Deflection → Tone → Execute.",
    },
    "sla-sweep": {
        "slug": "resolveai-sla-sweep",
        "label": "SLA Sweep",
        "description": "Cron-driven sweeper — rechecks open cases, escalates SLA-breach candidates.",
    },
    "post-resolution-qa": {
        "slug": "resolveai-post-qa",
        "label": "Post-Resolution QA",
        "description": "On case-close — rates tone+correctness, predicts CSAT, flags proactive outreach.",
    },
    "trend-mining": {
        "slug": "resolveai-trend-mining",
        "label": "Trend Mining / VoC",
        "description": "Nightly cross-ticket clustering — files a Voice-of-Customer case on anomaly.",
    },
}


# ─── Lifecycle ─────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("ResolveAI API starting on port %s", os.environ.get("PORT", "8004"))
    logger.info("Abenix URL: %s", os.environ.get("ABENIX_API_URL"))
    has_key = bool(os.environ.get("RESOLVEAI_ABENIX_API_KEY"))
    logger.info("Abenix SDK key configured: %s", has_key)
    logger.info("Persistence: %s", "postgres" if db_enabled else "in-memory")

    if db_enabled:
        try:
            await init_tables()
        except Exception as exc:  # noqa: BLE001
            logger.exception("init_tables() failed — continuing with degraded DB: %s", exc)

    # Pick store based on DATABASE_URL availability; attach to app.state
    # so routers can reach it through the get_store dependency.
    app.state.store = build_store()
    logger.info("CaseStore: %s", app.state.store.__class__.__name__)

    yield


app = FastAPI(title="ResolveAI API", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Mount routers ─────────────────────────────────────────────────────
app.include_router(cases_router.router)
app.include_router(admin_router.router)
app.include_router(sla_router.router)
app.include_router(qa_router.router)
app.include_router(trends_router.router)


# ─── Top-level endpoints preserved from the walking skeleton ───────────


@app.get("/health")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "resolveai-api",
        "persistence": "postgres" if db_enabled else "in-memory",
    }


@app.get("/api/resolveai/pipelines")
async def list_pipelines() -> dict[str, Any]:
    return {"data": [{"key": k, **v} for k, v in PIPELINES.items()]}


@app.get("/api/resolveai/metrics")
async def metrics(
    request: Request,
) -> dict[str, Any]:
    """Tenant-scoped aggregate over cases + cost."""
    store = get_store(request)
    tenant_id = get_tenant_id(request)
    data = await _maybe(store.metrics(tenant_id=tenant_id))
    return {"data": data}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8004"))
    uvicorn.run(app, host="0.0.0.0", port=port)
