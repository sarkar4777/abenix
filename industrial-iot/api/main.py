"""Industrial IoT API — thin FastAPI backend that fronts the showcase UI.

Self-contained: does not import Abenix app code at runtime. Uses the
bundled `abenix_sdk` to invoke platform agents/pipelines via API-key
delegation, matching the ContractIQ + Mideast Tourism standalone pattern.

Endpoints
GET  /health                                      liveness probe
GET  /api/industrial-iot/pipelines                catalog of demo pipelines
POST /api/industrial-iot/pipelines/{slug}/execute run a pipeline synchronously

Run locally:
    cd industrial-iot/api
    python main.py   # uses PORT env (default 8003)

Required environment:
    ABENIX_API_URL                   e.g. http://localhost:8000  (or cluster DNS)
    INDUSTRIALIOT_ABENIX_API_KEY     af_xxxxx — service-account key scoped to pipeline execution
    INDUSTRIALIOT_ACTING_SUBJECT_TYPE    default "industrial-iot"    (optional)
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

import httpx  # noqa: E402
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from abenix_sdk import Abenix, ActingSubject  # noqa: E402


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("industrial-iot")


# ─── Pipeline catalogue ────────────────────────────────────────────────
# The three showcase pipelines seeded under packages/db/seeds/agents/.
# Keyed by the URL-safe slug the UI passes in.
PIPELINES: dict[str, dict[str, Any]] = {
    "pump": {
        "slug": "iot-pump-pipeline",
        "label": "Pump Diagnostics & RUL Estimation",
        "description": (
            "Feeds FFT features from a vibration window into the pump-dsp analyser, "
            "fuses the spectral read-out with historical maintenance records, and "
            "emits a remaining-useful-life (RUL) estimate with a recommended action."
        ),
        "wait_seconds": 240,
        "required_assets": {
            "pump_dsp_asset_id": "pump-dsp-correction",
            "rul_asset_id": "rul-estimator",
        },
    },
    "cold-chain": {
        "slug": "iot-coldchain-pipeline",
        "label": "Cold-Chain Excursion Adjudicator",
        "description": (
            "Reconstructs the true temperature profile of a shipment from noisy "
            "sensor telemetry, adjudicates any excursions against policy, and "
            "decides whether to release, dispose, or trigger a claim."
        ),
        "wait_seconds": 240,
        "required_assets": {
            "cold_chain_asset_id": "cold-chain-corrector",
        },
    },
    "valueedge": {
        "slug": "iot-valueedge-pipeline",
        "label": "ValueEdge — Offshore-Wind FEED Designer",
        "description": (
            "From a one-line offshore-wind site brief, generates 3 distinct design "
            "scenarios, recomputes CapEx + CO2 + IRR + LCOE per scenario, ranks "
            "value-engineering opportunities, and drafts compliance RFIs against "
            "IEC 61400-3 / NEC 690 / IEEE 1547 / RWE-EPC."
        ),
        "wait_seconds": 240,
    },
    "bedrocc": {
        "slug": "iot-bedrocc-pipeline",
        "label": "BedROCC Operations Alarm Triage",
        "description": (
            "Operations control-room triage for a single SCADA alarm — runs the "
            "alarm classifier, cascade noise filter, and safe-reset advisor and "
            "returns a triage envelope the UI renders next to the alarm row."
        ),
        "wait_seconds": 120,
    },
    "fieldedge": {
        "slug": "iot-fieldedge-pipeline",
        "label": "FieldEdge Wind-Turbine Maintenance Copilot",
        "description": (
            "Voice/text symptom from a technician on the nacelle -> fleet-wide "
            "history search -> OEM-manual-grounded repair procedure with safety "
            "gates, parts, cited manual sections, and confidence."
        ),
        "wait_seconds": 180,
    },
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Industrial-IoT API starting on port %s", os.environ.get("PORT", "8003"))
    logger.info("Abenix URL: %s", os.environ.get("ABENIX_API_URL", "http://localhost:8000"))
    has_key = bool(os.environ.get("INDUSTRIALIOT_ABENIX_API_KEY"))
    logger.info("Abenix SDK key configured: %s", has_key)
    yield


app = FastAPI(
    title="Industrial IoT API",
    version="0.1.0",
    lifespan=lifespan,
)

try:
    from abenix_sdk.tracing import init_tracing as _init_tracing
    _init_tracing("industrial-iot-api", fastapi_app=app)
except Exception:
    pass

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _sdk() -> Abenix:
    key = os.environ.get("INDUSTRIALIOT_ABENIX_API_KEY", "")
    if not key:
        raise HTTPException(
            status_code=503,
            detail=(
                "INDUSTRIALIOT_ABENIX_API_KEY is not set on the industrial-iot-api "
                "pod. Create an api-key in Abenix and set the secret."
            ),
        )
    base_url = os.environ.get("ABENIX_API_URL", "http://localhost:8000")
    return Abenix(api_key=key, base_url=base_url, timeout=300.0)


def _acting_subject(request: Request) -> ActingSubject | None:
    """Use the request's X-Forwarded-User (or fallback anonymous) as the"""
    subject_type = os.environ.get("INDUSTRIALIOT_ACTING_SUBJECT_TYPE", "industrial-iot")
    user = request.headers.get("X-Forwarded-User") or "industrial-iot-ui"
    return ActingSubject(subject_type=subject_type, subject_id=user)


# ─── Proxy auth gate ───────────────────────────────────────────────────
# The platform-API passthroughs (/api/code-assets, /api/agents,
# /api/connectors) forward to abenix-api with the standalone's service-
# account X-API-Key — so any unauthenticated caller could otherwise act
# as the standalone's tenant from inside the cluster. The showcase has
# no user database, so the gate is a shared secret set by the Next.js
# web pod on every proxied request via server-side middleware. The
# secret is never exposed to the browser.
_WEB_PROXY_SECRET_ENV = "INDUSTRIALIOT_WEB_PROXY_SECRET"
_WEB_PROXY_HEADER = "X-IIOT-Web-Secret"


def _gate_proxy_request(request: Request) -> None:
    """Fail-closed gate: require X-IIOT-Web-Secret == env secret.

    401 when the env var is unset (so an undeployed-secret config never
    quietly leaks data) or when the header is missing / wrong.
    """
    expected = os.environ.get(_WEB_PROXY_SECRET_ENV, "").strip()
    if not expected:
        raise HTTPException(
            status_code=401,
            detail=(
                f"{_WEB_PROXY_SECRET_ENV} is not set on the industrial-iot-api "
                "pod — refusing to proxy platform-API traffic anonymously."
            ),
        )
    presented = (request.headers.get(_WEB_PROXY_HEADER) or "").strip()
    if not presented or presented != expected:
        raise HTTPException(status_code=401, detail="unauthorized proxy request")


# ─── Endpoints ─────────────────────────────────────────────────────────


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "industrial-iot-api"}


@app.get("/api/industrial-iot/pipelines")
async def list_pipelines() -> dict[str, Any]:
    return {
        "data": [
            {"key": k, **v}
            for k, v in PIPELINES.items()
        ],
    }


@app.get("/api/industrial-iot/live-status")
async def live_status() -> dict[str, Any]:
    """Best-effort reachability probe for the live-mode wiring.

    Returns simple booleans the LiveStatusPanel renders as ✓/✗ pills.
    Each leg is independent — if mosquitto is up but timescaledb is
    not, the UI shows that asymmetrically. We never raise here.
    """
    mqtt_host = os.environ.get("MQTT_BROKER_HOST", "localhost")
    mqtt_port = int(os.environ.get("MQTT_BROKER_PORT", "1883"))
    tsdb_host = os.environ.get("TSDB_HOST", "localhost")
    tsdb_port = int(os.environ.get("TSDB_PORT", "5433"))

    import socket
    def _reachable(host: str, port: int) -> bool:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.4)
                s.connect((host, port))
            return True
        except Exception:
            return False

    mqtt_ok = _reachable(mqtt_host, mqtt_port)
    tsdb_ok = _reachable(tsdb_host, tsdb_port)

    # Connector count — via SDK so auth + base URL are centralised. Fall
    # back to 0 if the connectors API is not wired up on this AgentForge yet.
    connectors = 0
    if os.environ.get("INDUSTRIALIOT_ABENIX_API_KEY"):
        try:
            async with _sdk() as forge:
                r = await forge.http.get("/api/connectors?limit=200", timeout=3.0)
                if r.status_code == 200:
                    items = r.json().get("data") or []
                    connectors = len(items) if isinstance(items, list) else 0
        except Exception:
            connectors = 0

    return {"data": {
        "mqtt": {"reachable": mqtt_ok, "broker": f"{mqtt_host}:{mqtt_port}"},
        "tsdb": {"reachable": tsdb_ok, "host": f"{tsdb_host}:{tsdb_port}"},
        "connectors": {"count": connectors},
    }}


@app.post("/api/industrial-iot/live/trigger")
async def live_trigger(request: Request) -> dict[str, Any]:
    """Toggle a simulator / listener agent's trigger on or off.

    The trigger registry on AgentForge isn't externalised yet; this
    endpoint is a thin shim that forwards to the platform's
    `/api/agents/{slug}/triggers` endpoint when present, and returns
    `{ok: true, accepted: false}` when not — letting the UI keep
    working in demo mode.
    """
    body = await request.json()
    slug = body.get("agent_slug") or ""
    enabled = bool(body.get("enabled", False))
    if not slug:
        raise HTTPException(status_code=400, detail="agent_slug is required")

    if not os.environ.get("INDUSTRIALIOT_ABENIX_API_KEY"):
        return {"ok": True, "accepted": False, "reason": "no_api_key"}

    try:
        async with _sdk() as forge:
            r = await forge.http.post(
                f"/api/agents/{slug}/triggers",
                json={"enabled": enabled},
                timeout=5.0,
            )
        if r.status_code == 404:
            # Trigger registry isn't externalised on abenix-api yet. Tell
            # the UI honestly so it can show "demo mode" rather than
            # green-lighting a non-existent subscription.
            return {
                "ok": False,
                "accepted": False,
                "status": 404,
                "reason": "live trigger not wired on platform yet",
            }
        return {"ok": r.is_success, "accepted": r.is_success, "status": r.status_code}
    except Exception as exc:
        logger.warning("trigger toggle forward failed: %s", exc)
        return {"ok": False, "accepted": False, "error": str(exc)}


@app.get("/api/industrial-iot/live/sse")
async def live_sse(topic: str) -> Response:
    """Bridge an MQTT topic into a Server-Sent-Events stream.

    The browser doesn't speak MQTT, so this endpoint subscribes on the
    server side via paho-mqtt (when installed) and pushes each message
    as one SSE frame. Falls back to an empty heartbeat stream when
    paho-mqtt isn't installed so the UI fails closed without errors.
    """
    import asyncio
    from fastapi.responses import StreamingResponse

    try:
        import paho.mqtt.client as mqtt  # type: ignore
    except ImportError:
        async def empty():
            # Heartbeats only. Lets the UI render the SSE wiring even
            # when the broker library isn't installed — production pods
            # always have it; dev laptops sometimes skip it.
            while True:
                yield ": heartbeat\n\n"
                await asyncio.sleep(15)
        return StreamingResponse(empty(), media_type="text/event-stream")

    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=200)
    loop = asyncio.get_running_loop()

    def on_message(_client, _userdata, msg):  # noqa: ANN001
        try:
            payload = msg.payload.decode("utf-8")
        except Exception:
            return
        # Hop back to the asyncio loop from paho's worker thread.
        loop.call_soon_threadsafe(lambda: queue.put_nowait(payload))

    client = mqtt.Client()
    client.on_message = on_message
    host = os.environ.get("MQTT_BROKER_HOST", "localhost")
    port = int(os.environ.get("MQTT_BROKER_PORT", "1883"))
    try:
        client.connect(host, port, keepalive=30)
    except Exception as exc:
        logger.warning("SSE bridge: cannot connect to MQTT %s:%d (%s)", host, port, exc)
        async def err():
            yield "event: error\ndata: {\"reachable\":false}\n\n"
        return StreamingResponse(err(), media_type="text/event-stream")
    client.subscribe(topic)
    client.loop_start()

    async def stream():
        try:
            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=15.0)
                    # SSE frames need data: prefix + double-newline. The
                    # browser EventSource auto-parses each frame.
                    yield f"data: {msg}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            client.loop_stop()
            try:
                client.disconnect()
            except Exception:
                pass

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/api/industrial-iot/subscribed-feeds/{feed_key}")
async def get_subscribed_feed(feed_key: str) -> dict[str, Any]:
    """Forward a subscribed_feed lookup so the ValueEdge tab can show
    when the BNEF coefficients were last refreshed."""
    if not os.environ.get("INDUSTRIALIOT_ABENIX_API_KEY"):
        return {"data": None}
    try:
        async with _sdk() as forge:
            r = await forge.http.get(f"/api/subscribed-feeds/{feed_key}", timeout=3.0)
            if r.status_code != 200:
                return {"data": None}
            return r.json()
    except Exception:
        return {"data": None}


@app.get("/api/industrial-iot/kb-status")
async def kb_status() -> dict[str, Any]:
    """Check whether the tenant has at least one knowledge base ready.

    The PumpTab + ColdChainTab show a yellow "KB Not Available" badge if
    this returns `available: false`, so users know adjudication will fall
    back to model defaults instead of citing tenant docs.
    """
    if not os.environ.get("INDUSTRIALIOT_ABENIX_API_KEY"):
        return {"data": {"available": False, "reason": "no_api_key"}}
    try:
        async with _sdk() as forge:
            # /api/knowledge-engines has no root listing — use the
            # collection-level endpoint that does (knowledge-bases).
            r = await forge.http.get("/api/knowledge-bases?limit=100", timeout=10.0)
            if r.status_code != 200:
                return {"data": {"available": False, "reason": f"http_{r.status_code}"}}
            payload = r.json()
            items = payload.get("data") or []
            if isinstance(items, dict):
                items = items.get("collections") or items.get("data") or []
            ready = [c for c in items if (c.get("status") in (None, "ready", "active"))]
            return {"data": {"available": bool(ready), "count": len(ready)}}
    except Exception as exc:
        logger.warning("kb-status probe failed: %s", exc)
        return {"data": {"available": False, "reason": "probe_error"}}


@app.post("/api/industrial-iot/pipelines/{pipeline_key}/execute")
async def execute_pipeline(pipeline_key: str, request: Request) -> JSONResponse:
    """Run one of the showcase pipelines synchronously."""
    cfg = PIPELINES.get(pipeline_key)
    if not cfg:
        raise HTTPException(status_code=404, detail=f"Unknown pipeline: {pipeline_key}")

    body = await request.json()
    message = body.get("message") or ""
    context = body.get("context") or {}

    if isinstance(message, (dict, list)):
        import json
        message = json.dumps(message)

    if message and "message" not in context:
        context["message"] = message

    asset_name_map = cfg.get("required_assets") or {}
    if asset_name_map:
        async with _sdk() as _forge:
            for ctx_key, asset_name in asset_name_map.items():
                if context.get(ctx_key):
                    continue
                try:
                    resp = await _forge.http.request(
                        "GET", "/api/code-assets?scope=all", timeout=10.0,
                    )
                    items = (resp.json() or {}).get("data") or []
                    hit = next(
                        (a for a in items
                         if a.get("status") == "ready"
                         and (a.get("name") == asset_name
                              or (a.get("name") or "").startswith(asset_name + "-"))),
                        None,
                    )
                    if hit:
                        context[ctx_key] = hit["id"]
                except Exception:
                    pass

    sdk = _sdk()
    try:
        result = await sdk.execute(
            cfg["slug"],
            message,
            act_as=_acting_subject(request),
            context=context,
            wait_timeout_seconds=cfg["wait_seconds"],
        )
    except Exception as exc:
        logger.exception("pipeline execute failed")
        return JSONResponse(
            status_code=502,
            content={"ok": False, "error": str(exc)},
        )
    finally:
        try:
            await sdk.close()
        except Exception:
            pass

    # SDK ExecutionResult doesn't carry execution_id directly — pull it
    # from tool_calls (where the runtime stamps the watch handle) or fall
    # back to None. Drop the field rather than 500 the whole response.
    exec_id = getattr(result, "execution_id", None)
    if not exec_id:
        for tc in (getattr(result, "tool_calls", None) or []):
            cand = (tc.get("execution_id") if isinstance(tc, dict) else None)
            if cand:
                exec_id = cand
                break

    # The SDK return shape stamps status="completed" even when the
    # underlying execution failed — the truth lives on the platform's
    # execution record. Re-fetch /api/executions/{id} so the UI sees the
    # real per-node status, tokens, cost, and any error surface. See
    # MEMORY: feedback_failure_visibility.
    status = (getattr(result, "status", None) or "completed").lower()
    node_results: dict[str, Any] = getattr(result, "node_results", None) or {}
    input_tokens = int(getattr(result, "input_tokens", 0) or 0)
    output_tokens = int(getattr(result, "output_tokens", 0) or 0)
    cost = float(getattr(result, "cost", 0) or 0)
    duration_ms = int(getattr(result, "duration_ms", 0) or 0)
    error_message: str | None = None
    failure_code: str | None = None

    if exec_id:
        try:
            forge = _sdk()
            try:
                rec = await forge.executions.get(exec_id)
            finally:
                try:
                    await forge.close()
                except Exception:
                    pass
            payload = (rec or {}).get("data") if isinstance(rec, dict) else None
            if not payload and isinstance(rec, dict):
                payload = rec
            if isinstance(payload, dict):
                raw_status = payload.get("status")
                if isinstance(raw_status, str) and raw_status:
                    status = raw_status.lower()
                if payload.get("node_results") is not None:
                    node_results = payload.get("node_results") or {}
                if payload.get("input_tokens") is not None:
                    input_tokens = int(payload.get("input_tokens") or 0)
                if payload.get("output_tokens") is not None:
                    output_tokens = int(payload.get("output_tokens") or 0)
                # Platform serialises as `cost` (USD float). Accept either key.
                if payload.get("cost") is not None:
                    cost = float(payload.get("cost") or 0)
                elif payload.get("cost_usd") is not None:
                    cost = float(payload.get("cost_usd") or 0)
                if payload.get("duration_ms") is not None:
                    duration_ms = int(payload.get("duration_ms") or 0)
                error_message = payload.get("error_message") or None
                failure_code = payload.get("failure_code") or None
        except Exception as exc:
            # The follow-up fetch is advisory — never mask the execute
            # result. Log and continue with the SDK numbers.
            logger.warning("execution detail fetch failed for %s: %s", exec_id, exc)

    # Surface per-node failures so the UI can red-flag the failing step
    # even when the overall status string was already "failed".
    node_errors: list[dict[str, Any]] = []
    if isinstance(node_results, dict):
        for nid, nval in node_results.items():
            if isinstance(nval, dict):
                nstatus = (nval.get("status") or "").lower()
                nerr = nval.get("error") or nval.get("error_message")
                if nstatus == "failed" or nerr:
                    node_errors.append({
                        "node_id": nid,
                        "status": nstatus or "failed",
                        "error": nerr,
                    })

    sdk_errors = list(getattr(result, "errors", None) or [])
    ok = status != "failed"
    body: dict[str, Any] = {
        "ok": ok,
        "status": status,
        "execution_id": exec_id,
        "final_output": result.output,
        "node_results": node_results,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost": cost,
        "duration_ms": duration_ms,
    }
    if not ok or error_message or sdk_errors or node_errors:
        body["error"] = error_message or (
            sdk_errors[0].get("message") if sdk_errors and isinstance(sdk_errors[0], dict)
            else None
        )
        if failure_code:
            body["failure_code"] = failure_code
        if sdk_errors:
            body["errors"] = sdk_errors
        if node_errors:
            body["node_errors"] = node_errors
    return JSONResponse(body, status_code=200 if ok else 502)


# ─── Platform-API passthrough ──────────────────────────────────────────
# Forwards /api/code-assets/* and /api/agents/* to abenix-api with the
# seeded service-account key so the showcase web doesn't have to expose
# Abenix credentials in the browser. Read-only or upload-style routes
# only — execution stays in the explicit pipelines endpoint above.
# /api/approvals is deliberately NOT on this list — HITL approvals carry
# business decisions and never go through an anonymous read path.
_PASSTHROUGH_PREFIXES = (
    "/api/code-assets",
    "/api/agents",
    "/api/connectors",
)
_HOP_BY_HOP_HEADERS = {
    "host", "content-length", "transfer-encoding", "connection",
    "keep-alive", "proxy-authenticate", "proxy-authorization", "te",
    "trailers", "upgrade",
}


async def _proxy(request: Request, path: str) -> Response:
    """Forward `path` to abenix-api with the standalone's API key."""
    # Gate-in-front of the SDK so an unauthenticated in-cluster request
    # cannot impersonate the standalone's tenant. The actAs delegation
    # below only happens after this check passes.
    _gate_proxy_request(request)
    full = f"/{path.lstrip('/')}"
    if not any(full == p or full.startswith(p + "/") or full.startswith(p + "?")
               for p in _PASSTHROUGH_PREFIXES):
        raise HTTPException(status_code=404, detail=f"no proxy route for {full}")

    # Build forward headers: drop hop-by-hop + auth (the SDK injects its own
    # X-API-Key). Forward acting-subject if present.
    fwd_headers: dict[str, str] = {}
    for k, v in request.headers.items():
        kl = k.lower()
        if kl in _HOP_BY_HOP_HEADERS or kl == "x-api-key":
            continue
        fwd_headers[k] = v
    subject = _acting_subject(request)
    if subject:
        fwd_headers["X-Abenix-Subject"] = subject.to_header()

    body = await request.body()
    relative_path = full
    if request.url.query:
        relative_path = f"{relative_path}?{request.url.query}"

    try:
        async with _sdk() as forge:
            up = await forge.http.request(
                request.method, relative_path, content=body or None,
                headers=fwd_headers, timeout=120.0,
            )
    except httpx.HTTPError as exc:
        logger.exception("proxy forward failed: %s", relative_path)
        return JSONResponse(
            status_code=502,
            content={"data": None, "error": f"upstream unreachable: {exc}", "meta": None},
        )

    # Strip hop-by-hop response headers; keep content-type so JSON is parsed.
    out_headers = {
        k: v for k, v in up.headers.items()
        if k.lower() not in _HOP_BY_HOP_HEADERS
    }
    return Response(
        content=up.content, status_code=up.status_code,
        headers=out_headers,
        media_type=up.headers.get("content-type"),
    )


@app.post("/api/industrial-iot/edge/compile-and-deploy")
async def edge_compile_and_deploy(request: Request) -> JSONResponse:
    """Resolve an agent slug + gateway id, compile the bundle, and deploy.

    Front-ends the two-step `compile -> deploy` dance with one POST so
    the PumpTab can stay simple. Returns the deploy envelope unchanged.
    """
    body = await request.json()
    agent_slug = (body.get("agent_slug") or "").strip()
    gateway_id_or_pk = (body.get("gateway_id") or "").strip()
    if not agent_slug:
        raise HTTPException(status_code=400, detail="agent_slug is required")

    if not os.environ.get("INDUSTRIALIOT_ABENIX_API_KEY"):
        raise HTTPException(status_code=503, detail="no api key on industrial-iot pod")

    async with _sdk() as forge:
        ar = await forge.http.get("/api/agents?limit=500", timeout=60.0)
        if ar.status_code != 200:
            raise HTTPException(status_code=502, detail=f"agents lookup http {ar.status_code}")
        raw = ar.json().get("data") or {}
        items = raw.get("agents") or raw.get("items") or raw if isinstance(raw, list) else (raw.get("agents") or raw.get("items") or [])
        agent = next((a for a in items if a.get("slug") == agent_slug), None)
        if not agent:
            return JSONResponse(
                status_code=404,
                content={
                    "ok": False,
                    "error": "agent_not_seeded",
                    "agent_slug": agent_slug,
                    "hint": "Run `python /app/packages/db/seeds/seed_agents.py` to register iot-pump-edge-classifier",
                },
            )

        gr = await forge.http.get("/api/edge/gateways", timeout=60.0)
        if gr.status_code != 200:
            raise HTTPException(status_code=502, detail=f"gateways lookup http {gr.status_code}")
        gateways = (gr.json().get("data") or {}).get("gateways") or []
        gw = None
        if gateway_id_or_pk:
            gw = next(
                (g for g in gateways if g.get("gateway_id") == gateway_id_or_pk
                 or g.get("id") == gateway_id_or_pk),
                None,
            )
        if not gw and gateways:
            gw = gateways[0]
        if not gw:
            return JSONResponse(
                status_code=404,
                content={
                    "ok": False,
                    "error": "no_gateway",
                    "hint": "Register an edge gateway first (helm install abenix-edge).",
                },
            )

        dr = await forge.http.post(
            f"/api/edge/gateways/{gw['id']}/deploy",
            json={"agent_id": agent["id"]},
            timeout=60.0,
        )
        deploy_body = {}
        try:
            deploy_body = dr.json()
        except Exception:
            deploy_body = {"raw": dr.text}
        return JSONResponse({
            "ok": dr.is_success,
            "agent": {"id": agent["id"], "slug": agent["slug"], "name": agent.get("name")},
            "gateway": {
                "id": gw["id"],
                "gateway_id": gw.get("gateway_id"),
                "name": gw.get("name"),
                "endpoint_url": gw.get("endpoint_url"),
            },
            "deploy": deploy_body,
        }, status_code=200 if dr.is_success else 502)


@app.post("/api/industrial-iot/edge/execute")
async def edge_execute(request: Request) -> JSONResponse:
    """Send a payload to the edge runtime running an agent slug.

    Resolves the gateway endpoint from the platform registry. Falls back
    to the cluster-internal abenix-edge service when the registered
    endpoint_url is empty (in-cluster runtime case).
    """
    import time
    body = await request.json()
    agent_slug = (body.get("agent_slug") or "").strip()
    payload = body.get("payload")
    gateway_id_or_pk = (body.get("gateway_id") or "").strip()
    if not agent_slug or payload is None:
        raise HTTPException(status_code=400, detail="agent_slug + payload required")

    if not os.environ.get("INDUSTRIALIOT_ABENIX_API_KEY"):
        raise HTTPException(status_code=503, detail="no api key on industrial-iot pod")

    async with _sdk() as forge:
        gr = await forge.http.get("/api/edge/gateways", timeout=30.0)
        gateways = (gr.json().get("data") or {}).get("gateways") or []
        gw = None
        if gateway_id_or_pk:
            gw = next(
                (g for g in gateways if g.get("gateway_id") == gateway_id_or_pk
                 or g.get("id") == gateway_id_or_pk),
                None,
            )
        if not gw and gateways:
            gw = gateways[0]

        endpoint = ""
        bundle_digest = None
        if gw:
            endpoint = (gw.get("endpoint_url") or "").rstrip("/")
            for d in (gw.get("deployed_agents") or []):
                if d.get("slug") == agent_slug:
                    bundle_digest = d.get("digest")
                    break
        if not endpoint:
            endpoint = os.environ.get(
                "EDGE_RUNTIME_INTERNAL_URL",
                "http://abenix-edge.abenix.svc.cluster.local:8080",
            ).rstrip("/")

        target = f"{endpoint}/agents/{agent_slug}/execute"
        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=30.0) as _hc:
                er = await _hc.post(target, json=payload)
        except Exception as exc:
            return JSONResponse(
                status_code=502,
                content={
                    "ok": False,
                    "error": f"edge unreachable: {exc}",
                    "endpoint": target,
                    "bundle_digest": bundle_digest,
                },
            )
        latency_ms = int((time.perf_counter() - t0) * 1000)

        try:
            data = er.json()
        except Exception:
            data = {"raw": er.text}
        return JSONResponse({
            "ok": er.is_success,
            "status": er.status_code,
            "endpoint": target,
            "edge_latency_ms": latency_ms,
            "bundle_digest": bundle_digest,
            "result": data,
            "gateway": {"id": gw.get("id") if gw else None,
                        "gateway_id": gw.get("gateway_id") if gw else None},
        })


@app.api_route("/api/code-assets", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy_code_assets_root(request: Request) -> Response:
    return await _proxy(request, "/api/code-assets")


@app.api_route("/api/code-assets/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy_code_assets(request: Request, rest: str) -> Response:
    return await _proxy(request, f"/api/code-assets/{rest}")


@app.api_route("/api/agents", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy_agents_root(request: Request) -> Response:
    return await _proxy(request, "/api/agents")


@app.api_route("/api/agents/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy_agents(request: Request, rest: str) -> Response:
    return await _proxy(request, f"/api/agents/{rest}")


@app.api_route("/api/connectors", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy_connectors_root(request: Request) -> Response:
    return await _proxy(request, "/api/connectors")


@app.api_route("/api/connectors/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy_connectors(request: Request, rest: str) -> Response:
    return await _proxy(request, f"/api/connectors/{rest}")


# /api/approvals intentionally has no passthrough route — HITL approvals
# are business decisions that must never be served through an anonymous
# in-cluster proxy. Any UI surface that needs approvals must call abenix
# directly through an authenticated session, not via this standalone.


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8003"))
    uvicorn.run(app, host="0.0.0.0", port=port)
