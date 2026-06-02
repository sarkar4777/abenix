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


_AGENT_ID_CACHE: dict[str, str] = {}


async def _resolve_agent_id(slug: str) -> str | None:
    """Look up agent UUID by slug. Cached per process."""
    if slug in _AGENT_ID_CACHE:
        return _AGENT_ID_CACHE[slug]
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"{ABENIX_URL}/api/agents", headers=_headers(), params={"search": slug, "limit": "10"})
            if r.status_code >= 400:
                return None
            j = r.json()
            for a in (j.get("data") or j.get("items") or []):
                if a.get("slug") == slug:
                    _AGENT_ID_CACHE[slug] = a["id"]
                    return a["id"]
    except Exception:
        pass
    return None


async def _execute_agent(slug: str, payload: dict) -> dict:
    """Fire-and-collect: resolve slug -> UUID, POST /api/agents/<uuid>/execute with the
    platform's ExecuteRequest shape ({message, context, wait}), and return the parsed
    JSON output plus execution_id so the browser DAG drawer can subscribe."""
    import json as _json
    agent_id = await _resolve_agent_id(slug)
    if not agent_id:
        return {"status": "failed", "error": f"agent slug '{slug}' not found in Abenix. Run seed_agents.py."}
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            r = await client.post(
                f"{ABENIX_URL}/api/agents/{agent_id}/execute",
                headers={**_headers(), "Content-Type": "application/json"},
                json={"message": _json.dumps(payload), "context": payload, "wait": True, "stream": False, "wait_timeout_seconds": 240},
            )
            if r.status_code >= 400:
                return {"status": "failed", "error": f"abenix returned {r.status_code}", "body": r.text[:600]}
            j = r.json()
            data = j.get("data") or j
            output_text = (
                data.get("output")
                or data.get("final_output")
                or data.get("result")
                or data.get("output_message")
                or ""
            )
            import asyncio as _asyncio

            exec_id = data.get("execution_id")
            if (not output_text or not str(output_text).strip()) and exec_id:
                for _delay in (0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 6.0):
                    try:
                        er = await client.get(
                            f"{ABENIX_URL}/api/executions/{exec_id}",
                            headers=_headers(),
                        )
                        if er.status_code < 400:
                            ej = er.json()
                            edata = ej.get("data") or ej
                            cand = (
                                edata.get("output_message")
                                or edata.get("output")
                                or edata.get("final_output")
                                or edata.get("result")
                                or ""
                            )
                            if cand and str(cand).strip():
                                output_text = cand
                                break
                            if edata.get("status") in ("failed", "error", "cancelled"):
                                break
                    except Exception:
                        pass
                    await _asyncio.sleep(_delay)
            parsed: dict = {}
            if isinstance(output_text, dict):
                parsed = output_text
            elif isinstance(output_text, str) and output_text.strip():
                s = output_text.strip()
                try:
                    parsed = _json.loads(s)
                except Exception:
                    import re as _re

                    m = _re.search(r"```(?:json)?\s*(\{[\s\S]*\})\s*```", s)
                    if m:
                        try:
                            parsed = _json.loads(m.group(1))
                        except Exception:
                            parsed = {}
                    if not parsed:
                        a, b = s.find("{"), s.rfind("}")
                        if a >= 0 and b > a:
                            try:
                                parsed = _json.loads(s[a : b + 1])
                            except Exception:
                                parsed = {}
            parsed.setdefault("execution_id", data.get("execution_id"))
            parsed.setdefault("cost_usd", data.get("cost"))
            parsed.setdefault("duration_ms", data.get("duration_ms"))
            return parsed or data
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
    """Call the platform ML predict endpoint for one (model_name, feature_vector) and
    enrich with feature contributions derived from training metrics + feature columns.
    Output is the same shape the SHAP code-asset would have returned."""
    import json as _json

    model_name = payload.get("model_name") or ""
    feature_vector: dict = payload.get("feature_vector") or {}
    if not model_name:
        return JSONResponse({"ok": False, "error": "model_name required"})
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(
                f"{ABENIX_URL}/api/ml-models",
                headers=_headers(),
                params={"search": model_name, "limit": "10"},
            )
            if r.status_code >= 400:
                return JSONResponse({"ok": False, "error": f"ml-models list returned {r.status_code}"})
            items = (r.json().get("data") or r.json().get("items") or [])
            model_row = next((m for m in items if m.get("name") == model_name), None)
            if not model_row:
                return JSONResponse({"ok": False, "error": f"model {model_name} not registered"})
            model_id = model_row["id"]
            metrics = model_row.get("training_metrics") or {}
            cols = list(feature_vector.keys())

            pr = await client.post(
                f"{ABENIX_URL}/api/ml-models/{model_id}/predict",
                headers={**_headers(), "Content-Type": "application/json"},
                json={"input_data": feature_vector},
            )
            prediction = None
            if pr.status_code < 400:
                pj = pr.json()
                pdata = pj.get("data") or pj
                p = pdata.get("prediction") or pdata.get("output") or pdata.get("result")
                if isinstance(p, list) and p:
                    prediction = float(p[0]) if isinstance(p[0], (int, float)) else None
                elif isinstance(p, (int, float)):
                    prediction = float(p)

        contributions = [{"feature": c, "value": float(feature_vector.get(c) or 0)} for c in cols]
        contributions.sort(key=lambda c: abs(c["value"]), reverse=True)
        return JSONResponse({
            "ok": True,
            "method": "ml-predict + feature-magnitude (SHAP code-asset not registered)",
            "model_name": model_name,
            "prediction": prediction,
            "feature_columns": cols,
            "contributions": contributions,
            "training_metrics": metrics,
        })
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
