"""QuoteIQ API: RFQ emails for a wire and cable manufacturer, quoted on Abenix.

A thin app. The inbox, the drafts and their reviews are local; reading the
email, finding each line's product, deciding the outcome and drafting the reply
are an Abenix pipeline reached through the SDK. Every draft is an Abenix
approval before it goes out.
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core import reviews, runs
from app.core.abenix import cancel_all, spawn
from app.core.config import settings
from app.core.emails import emails_dir, load_emails
from app.core.store import build_store
from app.routers import emails, health
from app.routers import reviews as review_routes

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("quoteiq")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    store = build_store()
    connect = getattr(store, "connect", None)
    if connect is not None:
        await connect()
    inbox = load_emails()
    await store.load(inbox)
    app.state.store = store
    logger.info(
        "QuoteIQ API up: store=%s emails=%d from %s pipeline=%s staff=%s",
        type(store).__name__, len(inbox), emails_dir(), settings.pipeline_slug, settings.staff_name,
    )
    if not settings.api_key:
        logger.warning("QUOTEIQ_ABENIX_API_KEY is not set; every run will be refused until it is.")
    await runs.resume(store)
    poller = spawn(reviews.poll_forever(store), name="approval-poller")
    try:
        yield
    finally:
        poller.cancel()
        await cancel_all()
        await asyncio.sleep(0)


app = FastAPI(
    title="QuoteIQ API",
    description=(
        "Reads request-for-quotation emails, finds each line's product in a mock "
        "ERP, and drafts a quote or a clarification for a person to review, or "
        "escalates the RFQ to staff. Every step runs on Abenix."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        o.strip()
        for o in os.environ.get("QQ_CORS_ORIGINS", "http://localhost:3008,http://localhost:3000").split(",")
        if o.strip()
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(emails.router)
app.include_router(review_routes.router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8008")))
