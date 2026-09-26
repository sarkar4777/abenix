"""PharmaVigil API — adverse-event case intake and assessment.

A thin app. Case rows and review decisions are local; every assessment is an
Abenix pipeline reached through the SDK. There is no direct HTTP to the
platform anywhere in this service.
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.store import build_store
from app.routers import cases, health, signals

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("pharmavigil")

app = FastAPI(
    title="PharmaVigil API",
    description=(
        "Adverse-event intake, MedDRA coding, seriousness and causality "
        "assessment, disproportionality signal detection and regulatory "
        "narrative generation. Every assessment runs on Abenix."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        o.strip()
        for o in os.environ.get(
            "PV_CORS_ORIGINS",
            "http://localhost:3007,http://localhost:3000",
        ).split(",")
        if o.strip()
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(cases.router)
app.include_router(signals.router)


@app.on_event("startup")
async def startup() -> None:
    store = build_store()
    connect = getattr(store, "connect", None)
    if connect is not None:
        await connect()
    app.state.store = store
    kind = type(store).__name__
    logger.info("PharmaVigil API up — store=%s pipeline=%s", kind,
                os.environ.get("PV_PIPELINE_SLUG", "pharmavigil-assess"))
    if not os.environ.get("PHARMAVIGIL_ABENIX_API_KEY"):
        logger.warning(
            "PHARMAVIGIL_ABENIX_API_KEY is not set — assessments will 401 until it is."
        )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8007")))
