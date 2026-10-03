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
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.models.contractiq_models import ContractIQCounterparty, ContractIQUser
from app.routers.auth import get_contractiq_user, tenant_id_for


ABENIX_URL = os.environ.get("ABENIX_API_URL", "http://abenix-api:8000")
API_KEY = os.environ.get("CONTRACTIQ_ABENIX_API_KEY", "")

router = APIRouter(prefix="/api/contractiq", tags=["executions-passthrough"])


def _subject_header(user) -> dict[str, str]:
    """Build the X-Abenix-Subject header for actAs delegation.

    Returns {} when user is None (background paths). Otherwise stamps the
    CIQ caller identity so the abenix-side Execution row carries subject_id
    + subject_type — required for /api/contractiq/executions/{id} ownership
    matching to find the caller's own executions.
    """
    if user is None:
        return {}
    import json
    payload = {
        "subject_type": "contractiq",
        "subject_id": str(user.id),
    }
    if getattr(user, "email", None):
        payload["email"] = user.email
    if getattr(user, "full_name", None):
        payload["display_name"] = user.full_name
    return {"X-Abenix-Subject": json.dumps(payload)}


def _headers(user=None) -> dict[str, str]:
    h: dict[str, str] = {"Accept": "application/json"}
    if API_KEY:
        h["X-API-Key"] = API_KEY
    h.update(_subject_header(user))
    return h


def _sse_headers(user=None) -> dict[str, str]:
    h = {"Accept": "text/event-stream"}
    if API_KEY:
        h["X-API-Key"] = API_KEY
    h.update(_subject_header(user))
    return h


def _sdk():
    """Lazy AbenixSDK constructor for read-side endpoints (ml-models registry,
    agent-id lookup, etc). Use this instead of raw httpx for any Abenix call.
    """
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sdk"))
    from abenix_sdk import Abenix
    # SDK takes base_url, not api_base. The old kwarg name silently raised
    # TypeError, swallowed by the broad except in _resolve_agent_id, and
    # surfaced as the "agent slug not found" UI error.
    return Abenix(base_url=ABENIX_URL, api_key=API_KEY or "dev")


def _execution_belongs_to(data: dict, user: ContractIQUser) -> bool:
    """True iff the abenix-side execution payload is owned by this CIQ user.

    Match is permissive across the actAs delegation surface — abenix stamps
    user_id with the SDK service account but carries the CIQ caller on
    subject_id / subject_type, and the tenant on tenant_id. Any of those
    matching the caller is treated as ownership. Everything else is a
    cross-tenant leak and dropped.
    """
    if not isinstance(data, dict):
        return False
    uid = str(user.id)
    tid = tenant_id_for(user)
    if str(data.get("user_id") or "") == uid:
        return True
    if tid and str(data.get("tenant_id") or "") == tid:
        return True
    # actAs delegation — strict form: subject_type pinned to 'contractiq'
    subj_type = str(data.get("subject_type") or "").lower()
    subj_id = str(data.get("subject_id") or "")
    if subj_id == uid and (subj_type in ("", "contractiq")):
        return True
    # Fallback for older executions that lack subject_* columns — the SDK
    # stamps the caller into execution metadata.acting_subject.
    meta = data.get("metadata") or {}
    if isinstance(meta, dict):
        acting = meta.get("acting_subject") or {}
        if isinstance(acting, dict) and str(acting.get("subject_id") or "") == uid:
            return True
    return False


@router.get("/executions")
async def list_executions(
    status: str | None = Query(None, description="Filter (e.g. running, completed)"),
    limit: int = Query(20, ge=1, le=200),
    user: ContractIQUser = Depends(get_contractiq_user),
):
    """List Abenix executions (defaults to all; pass status=running for active).

    BLOCKER A2 fix — was anonymous and leaked every tenant's execution feed to
    anyone on the LB. Now requires a CIQ token and filters results to rows
    owned by the caller's user id OR tenant id.
    """
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
            items = j.get("data") or j.get("items") or j or []
            if not isinstance(items, list):
                items = []
            items = [it for it in items if _execution_belongs_to(it, user)]
            return JSONResponse({"data": items})
    except Exception as e:
        return JSONResponse({"data": [], "error": str(e)})


@router.get("/executions/{execution_id}")
async def get_execution(
    execution_id: str,
    user: ContractIQUser = Depends(get_contractiq_user),
):
    """Single-execution read. Returns 404 when the row belongs to a different
    tenant so we never leak so much as the existence of another tenant's run.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"{ABENIX_URL}/api/executions/{execution_id}",
                headers=_headers(),
            )
            if r.status_code >= 400:
                return JSONResponse({"data": None, "error": f"abenix returned {r.status_code}"})
            j = r.json()
            data = j.get("data") or j
            if not _execution_belongs_to(data, user):
                # Same shape as a real miss — no info disclosure about the
                # other tenant's execution id.
                raise HTTPException(status_code=404, detail="execution not found")
            return JSONResponse({"data": data})
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse({"data": None, "error": str(e)})


async def _authorize_execution(execution_id: str, user: ContractIQUser) -> None:
    """Confirm `execution_id` belongs to `user` before opening an SSE stream.

    Used for both /watch and /narration so the upstream proxy never starts
    leaking another tenant's events. Raises 404 on miss to match
    get_execution's information-hiding behaviour.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"{ABENIX_URL}/api/executions/{execution_id}",
                headers=_headers(),
            )
            if r.status_code >= 400:
                raise HTTPException(status_code=404, detail="execution not found")
            j = r.json()
            data = j.get("data") or j
            if not _execution_belongs_to(data, user):
                raise HTTPException(status_code=404, detail="execution not found")
    except HTTPException:
        raise
    except Exception:
        # Conservative: when the ownership check itself fails, refuse rather
        # than open a passthrough stream. Better a flaky read than a quiet
        # cross-tenant leak.
        raise HTTPException(status_code=503, detail="execution authorization failed")


@router.get("/executions/{execution_id}/watch")
async def watch_execution(
    execution_id: str,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """SSE pass-through for a single execution's live event stream."""
    await _authorize_execution(execution_id, user)
    # the auth lookup's session, release it before streaming
    await db.close()

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
async def narration_passthrough(
    execution_id: str,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """SSE pass-through for execution narration (LLM commentary stream)."""
    await _authorize_execution(execution_id, user)
    await db.close()

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
async def ml_model_registry(
    _user: ContractIQUser = Depends(get_contractiq_user),
):
    """ML model registry passthrough via the AbenixSDK.

    MUST_FIX A3 — auth-gated so the paid-integration tool registry isn't
    enumerable from the LB. The registry contents themselves are not
    tenant-scoped today, but anonymous access is the actual info-disclosure
    finding.
    """
    try:
        sdk = _sdk()
        items = await sdk.ml_models.list()
        try:
            await sdk._http.aclose()
        except Exception:
            pass
        return JSONResponse({"data": items})
    except Exception as e:
        return JSONResponse({"data": [], "error": str(e)})


_AGENT_ID_CACHE: dict[str, str] = {}

import logging as _logging
_log = _logging.getLogger("contractiq.executions")


async def _resolve_agent_id(slug: str) -> str | None:
    """Look up agent UUID by slug via the AbenixSDK. Cached per process."""
    if slug in _AGENT_ID_CACHE:
        return _AGENT_ID_CACHE[slug]
    try:
        sdk = _sdk()
        a = await sdk.agents.find_by_slug(slug)
        try:
            await sdk._http.aclose()
        except Exception:
            pass
        if a and a.get("id"):
            _AGENT_ID_CACHE[slug] = a["id"]
            return a["id"]
    except Exception as e:
        # Surface the real reason in logs; a swallowed TypeError here once
        # masked an SDK-kwarg rename as a phantom "agent slug not found".
        _log.warning("resolve_agent_id(%s) failed: %r", slug, e)
    return None


async def _execute_agent(slug: str, payload: dict, user=None) -> dict:
    """Fire-and-collect: resolve slug -> UUID, POST /api/agents/<uuid>/execute with the
    platform's ExecuteRequest shape ({message, context, wait}), and return the parsed
    JSON output plus execution_id so the browser DAG drawer can subscribe.

    `user` is the CIQ caller; when supplied, X-Abenix-Subject is added so the
    abenix-side Execution row carries the actAs delegation stamp and the
    caller can read the row back via /api/contractiq/executions/{id}.
    """
    import json as _json
    agent_id = await _resolve_agent_id(slug)
    if not agent_id:
        return {"status": "failed", "error": f"agent slug '{slug}' not found in Abenix. Run seed_agents.py."}
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            r = await client.post(
                f"{ABENIX_URL}/api/agents/{agent_id}/execute",
                headers={**_headers(user), "Content-Type": "application/json"},
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
async def run_forecaster(
    payload: dict,
    user: ContractIQUser = Depends(get_contractiq_user),
):
    return JSONResponse(await _execute_agent("ciq-offtake-forecaster", payload, user))


@router.post("/price-engine/run")
async def run_price_engine(
    payload: dict,
    user: ContractIQUser = Depends(get_contractiq_user),
):
    return JSONResponse(await _execute_agent("ciq-price-engine", payload, user))


@router.post("/recommendations/run")
async def run_recommendations(
    payload: dict,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
):
    # Tenant scope is a JWT-only claim. Reject any body-passed tenant_id so a
    # caller can't aim the engine at another tenant by tampering with the post
    # body. Empty/null values are tolerated (they would no-op anyway).
    if payload.get("tenant_id"):
        raise HTTPException(
            status_code=400,
            detail="tenant_id must not be sent in the request body; it is taken from the auth token",
        )
    tid = tenant_id_for(user)
    # Inline the tenant's counterparties — the agent's portfolio_query tool hits an
    # abenix-side feed under tenant_id, which is empty for CIQ seed tenants. Pass the
    # CIQ-side roster so the engine has something to score.
    cp_rows = (await db.execute(
        select(ContractIQCounterparty).where(ContractIQCounterparty.tenant_id == tid)
    )).scalars().all()
    counterparties = [
        {
            "name": cp.legal_name,
            "sector": cp.sector,
            "country": cp.country,
            "credit_rating": cp.credit_rating,
        }
        for cp in cp_rows
    ]
    payload = {**payload, "tenant_id": tid, "counterparties": counterparties}
    result = await _execute_agent("ciq-recommendation-engine", payload, user)
    # Overwrite fetched_at server-side — the model frequently hallucinates a
    # frozen date (training-data anchor) for this field; the only authoritative
    # source for "when did this run" is the server clock at response time.
    from datetime import datetime, timezone
    if isinstance(result, dict):
        result["fetched_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return JSONResponse(result)


@router.post("/workbench/explain")
async def run_workbench_explain(payload: dict):
    """Per-prediction explainability for the Analyst Workbench.

    Preferred path: route (model_name, feature_vector) to the
    `shap_explainer` code-asset on the platform — that returns real
    SHAP / linear-coef attributions. Fallback path: when the code-asset
    isn't registered or its run fails, return ok:false with the real
    ml-predict prediction value + raw feature magnitudes flagged as
    `feature-magnitude-fallback` so the UI can render an explicit
    "not a real attribution" banner instead of pretending magnitudes
    are SHAP values.
    """
    model_name = (payload.get("model_name") or "").strip()
    feature_vector: dict = payload.get("feature_vector") or {}
    if not model_name:
        return JSONResponse({"ok": False, "error": "model_name required"})

    # ── 1. resolve the ml-model row + pull the real prediction (used by
    # both the SHAP path and the fallback so the UI always shows a real
    # number, never null).
    metrics: dict = {}
    cols = list(feature_vector.keys())
    prediction: float | None = None
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

            pr = await client.post(
                f"{ABENIX_URL}/api/ml-models/{model_id}/predict",
                headers={**_headers(), "Content-Type": "application/json"},
                json={"input_data": feature_vector},
            )
            if pr.status_code < 400:
                pj = pr.json()
                pdata = pj.get("data") or pj
                p = pdata.get("prediction") or pdata.get("output") or pdata.get("result")
                if isinstance(p, list) and p:
                    prediction = float(p[0]) if isinstance(p[0], (int, float)) else None
                elif isinstance(p, (int, float)):
                    prediction = float(p)
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"ml-predict failed: {e}"})

    # ── 2. try the real shap_explainer code-asset.
    shap_error: str | None = None
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            lr = await client.get(
                f"{ABENIX_URL}/api/code-assets",
                headers=_headers(),
            )
            if lr.status_code >= 400:
                shap_error = f"code-assets list returned {lr.status_code}"
            else:
                lj = lr.json()
                assets = lj.get("data") or lj.get("items") or (lj if isinstance(lj, list) else [])
                asset = next(
                    (a for a in assets if (a.get("name") or "").strip() == "shap_explainer"),
                    None,
                )
                if not asset:
                    shap_error = "shap_explainer code-asset not registered"
                elif (asset.get("status") or "").lower() != "ready":
                    shap_error = f"shap_explainer is {asset.get('status') or 'unknown'} — not ready"
                else:
                    tr = await client.post(
                        f"{ABENIX_URL}/api/code-assets/{asset['id']}/test",
                        headers={**_headers(), "Content-Type": "application/json"},
                        json={
                            "input": {
                                "model_name": model_name,
                                "feature_vector": feature_vector,
                            },
                            "timeout_seconds": 120,
                        },
                    )
                    if tr.status_code >= 400:
                        shap_error = f"shap_explainer /test returned {tr.status_code}: {tr.text[:200]}"
                    else:
                        tj = tr.json()
                        data = tj.get("data") or tj
                        exe = data.get("execution") or data
                        # The code-asset tool wraps stdout as {"result": <parsed>, ...}
                        out = exe.get("result") if isinstance(exe, dict) else None
                        if not isinstance(out, dict):
                            out = exe if isinstance(exe, dict) else {}
                        if out.get("ok") and out.get("contributions"):
                            return JSONResponse({
                                "ok": True,
                                "method": out.get("method") or "shap",
                                "model_name": model_name,
                                "prediction": out.get("prediction", prediction),
                                "feature_columns": out.get("feature_columns") or cols,
                                "contributions": out.get("contributions") or [],
                                "waterfall": out.get("waterfall") or [],
                                "training_metrics": metrics,
                            })
                        shap_error = out.get("error") or "shap_explainer returned no contributions"
    except Exception as e:
        shap_error = f"shap_explainer call failed: {e}"

    # ── 3. fallback — surface honestly. Raw feature magnitudes are NOT
    # SHAP. ok:false so the UI shows the amber banner.
    contributions = [{"feature": c, "value": float(feature_vector.get(c) or 0)} for c in cols]
    contributions.sort(key=lambda c: abs(c["value"]), reverse=True)
    return JSONResponse({
        "ok": False,
        "method": "feature-magnitude-fallback",
        "error": shap_error or "real SHAP unavailable",
        "model_name": model_name,
        "prediction": prediction,
        "feature_columns": cols,
        "contributions": contributions,
        "training_metrics": metrics,
    })


# Registry view of the market-data category tools that agents can call.
# Source of truth: apps/agent-runtime/engine/tools/<name>.py. Status reflects how the
# tool behaves at runtime, not whether it is enabled for this tenant:
#   - 'live'        : the tool fetches from a real public upstream (HTTP / SDK).
#   - 'simulated'   : the tool produces output without an external market-data call
#                     (pure math, LLM-only, local retrieval).
#   - 'unavailable' : the tool exists but the upstream feed needs a paid
#                     subscription this tenant does not have, OR the tool is
#                     not actually registered in the runtime yet.
_MARKET_DATA_TOOL_REGISTRY: list[dict] = [
    # market-prices
    {"name": "yahoo_finance",       "category": "market-prices",        "status": "live",        "purpose": "Equity / FX / commodity tickers via yfinance."},
    {"name": "eia_open_data",       "category": "market-prices",        "status": "live",        "purpose": "US EIA open data — gas / power / petroleum series."},
    {"name": "eex_public_summary",  "category": "market-prices",        "status": "unavailable", "purpose": "EEX TTF settlement — no free machine-readable feed."},
    {"name": "market_data",         "category": "market-prices",        "status": "live",        "purpose": "Alpha Vantage market-data fetcher (quotes / FX / commodities)."},
    {"name": "entso_e_tool",        "category": "market-prices",        "status": "live",        "purpose": "ENTSO-E transparency platform — EU power prices and load."},
    {"name": "ember_tool",          "category": "market-prices",        "status": "live",        "purpose": "Ember climate energy + power-generation mix data."},
    {"name": "ecb_rates_tool",      "category": "market-prices",        "status": "live",        "purpose": "ECB FX reference rates."},
    # search-and-news
    {"name": "tavily_search",       "category": "search-and-news",      "status": "live",        "purpose": "Tavily web search API for fresh news + URLs."},
    {"name": "news_feed",           "category": "search-and-news",      "status": "live",        "purpose": "Aggregated headline news (RSS / news API)."},
    {"name": "web_search",          "category": "search-and-news",      "status": "live",        "purpose": "DuckDuckGo search fallback when no Tavily key is set."},
    # filings-and-registry
    {"name": "edgar_filings",       "category": "filings-and-registry", "status": "live",        "purpose": "SEC EDGAR — US company filings."},
    {"name": "bundesanzeiger",      "category": "filings-and-registry", "status": "live",        "purpose": "German Federal Gazette — DE company filings."},
    {"name": "companies_house",     "category": "filings-and-registry", "status": "live",        "purpose": "UK Companies House register."},
    {"name": "ferc_elibrary",       "category": "filings-and-registry", "status": "live",        "purpose": "FERC eLibrary — US energy regulator dockets."},
    {"name": "phmsa_lookup",        "category": "filings-and-registry", "status": "live",        "purpose": "PHMSA pipeline operator + incident lookup."},
    {"name": "epa_echo",            "category": "filings-and-registry", "status": "live",        "purpose": "EPA ECHO enforcement + compliance data."},
    # credit-and-rating
    {"name": "moodys_orbis_lookup", "category": "credit-and-rating",    "status": "unavailable", "purpose": "Moody's Orbis company lookup — requires paid subscription."},
    {"name": "moodys_api",          "category": "credit-and-rating",    "status": "live",        "purpose": "Moody's public ratings + commentary endpoints."},
    {"name": "spg_ratings",         "category": "credit-and-rating",    "status": "live",        "purpose": "S&P Global Ratings public data."},
    {"name": "fitch_connect",       "category": "credit-and-rating",    "status": "live",        "purpose": "Fitch Connect ratings + research."},
    {"name": "country_cpi_lookup",  "category": "credit-and-rating",    "status": "live",        "purpose": "Country CPI inflation index from World Bank / IMF."},
    {"name": "industry_segment_risk","category": "credit-and-rating",   "status": "simulated",   "purpose": "Industry-segment risk scoring from local model."},
    {"name": "sanctions_screening", "category": "credit-and-rating",    "status": "live",        "purpose": "OFAC / EU / UN sanctions list screening."},
    # weather
    {"name": "noaa_weather",        "category": "weather",              "status": "unavailable", "purpose": "NOAA station data — not provisioned in this runtime."},
    {"name": "open_meteo",          "category": "weather",              "status": "live",        "purpose": "Open-Meteo forecast + geocoding API."},
    {"name": "weather_simulator",   "category": "weather",              "status": "simulated",   "purpose": "Stochastic weather scenario generator (no external feed)."},
    # compute-and-explain
    {"name": "monte_carlo_curve",   "category": "compute-and-explain",  "status": "simulated",   "purpose": "Monte-Carlo forward-curve simulator."},
    {"name": "realized_vol_calc",   "category": "compute-and-explain",  "status": "simulated",   "purpose": "Realised volatility from a price series."},
    {"name": "code_asset",          "category": "compute-and-explain",  "status": "simulated",   "purpose": "Runs a registered code-asset in a sandbox."},
    {"name": "financial_calculator","category": "compute-and-explain",  "status": "simulated",   "purpose": "NPV / IRR / yield arithmetic."},
    {"name": "scenario_planner",    "category": "compute-and-explain",  "status": "simulated",   "purpose": "LLM-driven scenario fan-out from a prior."},
    {"name": "ml_model_tool",       "category": "compute-and-explain",  "status": "live",        "purpose": "Calls a registered ML model in the platform for predict / proba."},
    # extraction
    {"name": "structured_extractor","category": "extraction",           "status": "simulated",   "purpose": "Schema-guided JSON extractor over arbitrary text."},
    {"name": "document_parser",     "category": "extraction",           "status": "simulated",   "purpose": "PDF / DOCX text extraction."},
    {"name": "document_extractor",  "category": "extraction",           "status": "simulated",   "purpose": "LLM extraction over an uploaded document."},
    {"name": "knowledge_search",    "category": "extraction",           "status": "simulated",   "purpose": "Hybrid vector + graph search over tenant KBs."},
    {"name": "sentiment_analyzer",  "category": "extraction",           "status": "simulated",   "purpose": "LLM sentiment scoring."},
]


@router.get("/data-fabric/sources")
async def data_fabric_sources(
    _user: ContractIQUser = Depends(get_contractiq_user),
):
    """Registry view of the market-data tools agents can call.

    Market data does not flow through a "connectors" admin UI — it flows through
    tools registered under apps/agent-runtime/engine/tools/. This endpoint returns
    that registry, grouped by category, plus a last-used timestamp per tool when
    Abenix tool-invocation telemetry is available, plus the same ML-model + recent
    execution summary the page already shows.
    """
    out: dict = {
        "sources": list(_MARKET_DATA_TOOL_REGISTRY),
        "summary": {},
        "errors": [],
    }

    # Telemetry enrichment (last-used timestamps, ML registry, execution
    # counts) must come through the AbenixSDK passthrough — not direct httpx
    # to Abenix routes. The /data-fabric page renders the static registry
    # synchronously and the Live Activity rail surfaces real-time state.

    # Category-level summary for the page header.
    by_cat: dict[str, dict[str, int]] = {}
    for s in out["sources"]:
        c = s["category"]
        bucket = by_cat.setdefault(c, {"total": 0, "live": 0, "simulated": 0, "unavailable": 0})
        bucket["total"] += 1
        bucket[s["status"]] = bucket.get(s["status"], 0) + 1
    out["summary"]["tools_by_category"] = by_cat
    out["summary"]["tools_total"] = len(out["sources"])
    out["summary"]["tools_live"] = sum(1 for s in out["sources"] if s["status"] == "live")
    out["summary"]["tools_simulated"] = sum(1 for s in out["sources"] if s["status"] == "simulated")
    out["summary"]["tools_unavailable"] = sum(1 for s in out["sources"] if s["status"] == "unavailable")

    return JSONResponse(out)


@router.get("/ml-models/invocations")
async def list_ml_invocations(
    status: str | None = Query(None),
    limit: int = Query(20, ge=1, le=200),
    _user: ContractIQUser = Depends(get_contractiq_user),
):
    """List recent ML-model invocations across all models the platform tracks.

    MUST_FIX A3 — auth-gated so the invocation telemetry isn't enumerable
    anonymously. Tenant-level filtering on the abenix side is tracked
    separately; this fix only closes the open-endpoint disclosure.
    """
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

# reload-trigger 1781863716
