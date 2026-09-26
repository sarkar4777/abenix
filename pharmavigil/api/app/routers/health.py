"""Health and platform-connectivity probes."""
from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter

from app.routers._deps import ASSESS_PIPELINE_SLUG

router = APIRouter(tags=["pv-health"])


@router.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "service": "pharmavigil-api"}


@router.get("/api/pv/platform")
async def platform() -> dict[str, Any]:
    """Whether the Abenix side is reachable and the pipeline is registered.

    Useful on a fresh install: an unreachable platform and a missing pipeline
    fail very differently and the UI should be able to say which.
    """
    from abenix_sdk import Abenix

    sdk = Abenix(
        base_url=os.environ.get("ABENIX_API_URL", "http://localhost:8000"),
        api_key=os.environ.get("PHARMAVIGIL_ABENIX_API_KEY", ""),
        timeout=float(os.environ.get("PV_PROBE_TIMEOUT_SECONDS", "8")),
    )
    out: dict[str, Any] = {
        "abenix_url": os.environ.get("ABENIX_API_URL", "http://localhost:8000"),
        "pipeline_slug": ASSESS_PIPELINE_SLUG,
        "api_key_set": bool(os.environ.get("PHARMAVIGIL_ABENIX_API_KEY")),
        "reachable": False,
        "pipeline_registered": False,
        "detail": None,
    }
    try:
        found = await sdk.agents.find_by_slug(ASSESS_PIPELINE_SLUG)
        out["reachable"] = True
        out["pipeline_registered"] = found is not None
        if not out["pipeline_registered"]:
            out["detail"] = "run seed_agents.py — the assessment pipeline is not registered"
    except Exception as exc:  # noqa: BLE001
        out["detail"] = str(exc)[:300]
    finally:
        try:
            await sdk.close()
        except Exception:  # noqa: BLE001
            pass
    return {"data": out, "error": None, "meta": None}
