"""Health and platform-connectivity probes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.core.abenix import describe, new_sdk
from app.core.config import settings
from app.routers._deps import ok

router = APIRouter(tags=["qq-health"])


@router.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "service": "quoteiq-api"}


@router.get("/api/qq/platform")
async def platform() -> dict[str, Any]:
    """Whether Abenix is reachable and the pipeline and drafter are registered.

    An unreachable platform and a missing agent fail very differently, and the
    UI should be able to say which.
    """
    out: dict[str, Any] = {
        "abenix_url": settings.abenix_url,
        "pipeline_slug": settings.pipeline_slug,
        "drafter_slug": settings.drafter_slug,
        "staff_name": settings.staff_name,
        "api_key_set": bool(settings.api_key),
        "reachable": False,
        "pipeline_registered": False,
        "drafter_registered": False,
        "detail": None,
    }
    sdk = new_sdk(timeout=8)
    try:
        out["pipeline_registered"] = await sdk.agents.by_slug(settings.pipeline_slug) is not None
        out["reachable"] = True
        out["drafter_registered"] = await sdk.agents.by_slug(settings.drafter_slug) is not None
        missing = [s for s, found in ((settings.pipeline_slug, out["pipeline_registered"]),
                                      (settings.drafter_slug, out["drafter_registered"])) if not found]
        if missing:
            out["detail"] = f"not registered in Abenix: {', '.join(missing)}. Run seed_agents.py"
    except Exception as exc:  # noqa: BLE001
        out["detail"] = describe(exc)[:300]
    finally:
        await sdk.close()
    return ok(out)
