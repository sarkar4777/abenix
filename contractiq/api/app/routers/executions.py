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


@router.get("/ml-models/registry")
async def ml_model_registry():
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"{ABENIX_URL}/api/ml-models", headers=_headers())
            if r.status_code >= 400:
                return JSONResponse({"data": [], "error": f"abenix returned {r.status_code}"})
            j = r.json()
            items = j.get("data") or j.get("items") or j or []
        return JSONResponse({"data": items})
    except Exception as e:
        return JSONResponse({"data": [], "error": str(e)})


async def _execute_agent(slug: str, payload: dict) -> dict:
    """Fire-and-collect: call Abenix /api/agents/<slug>/execute and return final_output."""
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(
                f"{ABENIX_URL}/api/agents/{slug}/execute",
                headers={**_headers(), "Content-Type": "application/json"},
                json={"input": payload},
            )
            if r.status_code >= 400:
                return {"status": "failed", "error": f"abenix returned {r.status_code}", "body": r.text[:600]}
            j = r.json()
            return j.get("data") or j
    except Exception as e:
        return {"status": "failed", "error": str(e)}


@router.post("/forecaster/run")
async def run_forecaster(payload: dict):
    return JSONResponse(await _execute_agent("ciq-offtake-forecaster", payload))


@router.post("/price-engine/run")
async def run_price_engine(payload: dict):
    return JSONResponse(await _execute_agent("ciq-price-engine", payload))


@router.post("/recommendations/run")
async def run_recommendations(payload: dict):
    return JSONResponse(await _execute_agent("ciq-recommendation-engine", payload))


@router.post("/workbench/explain")
async def run_workbench_explain(payload: dict):
    """Run the SHAP code-asset for one (model_name, feature_vector).
    Calls Abenix /api/code-assets/shap_explainer/run. Falls back to ml_model.explain
    if the code-asset isn't registered yet."""
    body = {"input": payload}
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(
                f"{ABENIX_URL}/api/code-assets/shap_explainer/run",
                headers={**_headers(), "Content-Type": "application/json"},
                json=body,
            )
            if r.status_code < 400:
                j = r.json()
                return JSONResponse(j.get("data") or j)
            r2 = await client.post(
                f"{ABENIX_URL}/api/ml-models/{payload.get('model_name', '')}/explain",
                headers={**_headers(), "Content-Type": "application/json"},
                json={"feature_vector": payload.get("feature_vector", {})},
            )
            if r2.status_code < 400:
                j2 = r2.json()
                return JSONResponse(j2.get("data") or j2)
        return JSONResponse({"ok": False, "error": "shap_explainer not registered + ml-models explain unavailable"})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


@router.get("/data-fabric/sources")
async def data_fabric_sources():
    """Live telemetry for the Data Fabric page. Pulls real Abenix telemetry:
    market_data_sources + recent ml_model_invocations + execution counts.
    Returns shape consumed by /data-fabric page; no hardcoded connectors."""
    out: dict = {"sources": [], "summary": {}, "errors": []}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                r = await client.get(f"{ABENIX_URL}/api/market-data/sources", headers=_headers())
                if r.status_code < 400:
                    j = r.json()
                    items = j.get("data") or j.get("items") or j or []
                    if isinstance(items, list):
                        out["sources"].extend([
                            {**i, "kind": i.get("kind") or "market-data"} for i in items
                        ])
            except Exception as e:
                out["errors"].append(f"market-data: {e}")

            try:
                r = await client.get(f"{ABENIX_URL}/api/ml-models", headers=_headers())
                if r.status_code < 400:
                    j = r.json()
                    items = j.get("data") or j.get("items") or j or []
                    if isinstance(items, list):
                        out["summary"]["ml_models_registered"] = len(items)
                        out["summary"]["ml_models"] = [
                            {"name": m.get("name"), "version": m.get("version"),
                             "status": m.get("status"), "framework": m.get("framework")}
                            for m in items[:50]
                        ]
            except Exception as e:
                out["errors"].append(f"ml-models: {e}")

            try:
                r = await client.get(
                    f"{ABENIX_URL}/api/executions",
                    headers=_headers(),
                    params={"limit": "200"},
                )
                if r.status_code < 400:
                    j = r.json()
                    items = j.get("data") or j.get("items") or j or []
                    if isinstance(items, list):
                        by_status: dict = {}
                        for it in items:
                            s = (it.get("status") or "unknown").lower()
                            by_status[s] = by_status.get(s, 0) + 1
                        out["summary"]["recent_executions_by_status"] = by_status
                        out["summary"]["recent_executions_total"] = len(items)
            except Exception as e:
                out["errors"].append(f"executions: {e}")
    except Exception as e:
        out["errors"].append(str(e))

    return JSONResponse(out)


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
