"""Read-only passthrough to the Abenix platform's executions + narration endpoints.

All execution / tool-call / ML-invocation logs live in Abenix — E&C-Copilot
stores nothing locally. These endpoints exist so the contractiq-web's
LiveActivityRail and DagDrawer can render live agent + model activity.

Auth flows: contractiq-web (browser, JWT) → contractiq-api (this router) →
abenix-api (service-account `CONTRACTIQ_ABENIX_API_KEY`).
"""

from __future__ import annotations

import os
from typing import AsyncIterator

import httpx
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse, StreamingResponse


ABENIX_URL = os.environ.get("ABENIX_API_URL", "http://abenix-api:8000")
API_KEY = os.environ.get("CONTRACTIQ_ABENIX_API_KEY", "")

router = APIRouter(prefix="/api/contractiq", tags=["executions-passthrough"])


def _headers() -> dict[str, str]:
    h: dict[str, str] = {"Accept": "application/json"}
    if API_KEY:
        h["X-API-Key"] = API_KEY
    return h


def _sse_headers() -> dict[str, str]:
    h = {"Accept": "text/event-stream"}
    if API_KEY:
        h["X-API-Key"] = API_KEY
    return h


@router.get("/executions")
async def list_executions(
    status: str | None = Query(None, description="Filter (e.g. running, completed)"),
    limit: int = Query(20, ge=1, le=200),
):
    """List Abenix executions (defaults to all; pass status=running for active)."""
    params: dict[str, str] = {"limit": str(limit)}
    if status:
        params["status"] = status
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"{ABENIX_URL}/api/executions/live" if status == "running" else f"{ABENIX_URL}/api/executions",
                headers=_headers(),
                params=params,
            )
            if r.status_code >= 400:
                return JSONResponse({"data": [], "error": f"abenix returned {r.status_code}"})
            j = r.json()
            return JSONResponse({"data": j.get("data") or j.get("items") or j or []})
    except Exception as e:
        return JSONResponse({"data": [], "error": str(e)})


@router.get("/executions/{execution_id}")
async def get_execution(execution_id: str):
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"{ABENIX_URL}/api/executions/{execution_id}",
                headers=_headers(),
            )
            if r.status_code >= 400:
                return JSONResponse({"data": None, "error": f"abenix returned {r.status_code}"})
            j = r.json()
            return JSONResponse({"data": j.get("data") or j})
    except Exception as e:
        return JSONResponse({"data": None, "error": str(e)})


@router.get("/executions/{execution_id}/watch")
async def watch_execution(execution_id: str) -> StreamingResponse:
    """SSE pass-through for a single execution's live event stream."""
    async def gen() -> AsyncIterator[bytes]:
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream(
                    "GET",
                    f"{ABENIX_URL}/api/executions/{execution_id}/watch",
                    headers=_sse_headers(),
                ) as upstream:
                    async for chunk in upstream.aiter_raw():
                        yield chunk
        except Exception:
            return

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/narration/{execution_id}")
async def narration_passthrough(execution_id: str) -> StreamingResponse:
    """SSE pass-through for execution narration (LLM commentary stream)."""
    async def gen() -> AsyncIterator[bytes]:
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream(
                    "GET",
                    f"{ABENIX_URL}/api/executions/{execution_id}/stream",
                    headers=_sse_headers(),
                ) as upstream:
                    async for chunk in upstream.aiter_raw():
                        yield chunk
        except Exception:
            return

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/ml-models/invocations")
async def list_ml_invocations(
    status: str | None = Query(None),
    limit: int = Query(20, ge=1, le=200),
):
    """List recent ML-model invocations across all models the platform tracks."""
    params: dict[str, str] = {"limit": str(limit)}
    if status:
        params["status"] = status
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"{ABENIX_URL}/api/ml-models/invocations",
                headers=_headers(),
                params=params,
            )
            if r.status_code >= 400:
                return JSONResponse({"data": []})
            j = r.json()
            return JSONResponse({"data": j.get("data") or j.get("items") or j or []})
    except Exception as e:
        return JSONResponse({"data": [], "error": str(e)})
