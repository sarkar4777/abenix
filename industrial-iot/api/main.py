"""Industrial IoT API — thin FastAPI backend that fronts the showcase UI.

Self-contained: does not import Abenix app code at runtime. Uses the
bundled `abenix_sdk` to invoke platform agents/pipelines via API-key
delegation, matching the the example app + Saudi Tourism standalone pattern.

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

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

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

    return JSONResponse({
        "ok": True,
        "status": "completed",
        "execution_id": result.execution_id,
        "final_output": result.output,
        "node_results": getattr(result, "node_results", None) or {},
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "cost": result.cost,
        "duration_ms": result.duration_ms,
    })


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8003"))
    uvicorn.run(app, host="0.0.0.0", port=port)
