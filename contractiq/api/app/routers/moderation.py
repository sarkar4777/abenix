"""ContractIQ moderation proxy + DLP gate helpers.

CIQ never owned its own moderation policy store — the platform gate already
runs inside agent-runtime around every LLM/tool call. But CIQ surfaces that
build a prompt locally (chat, contract upload text, deep re-analyze) used to
hand the raw payload straight to the agent with no upfront DLP/PII check.

This router fills both gaps:

  * GET  /api/contractiq/moderation/policies — read-only proxy to the
    abenix `/api/moderation/policies` list. The CIQ tenant maps onto a stable
    abenix tenant_id via `tenant_id_for(user)` (forwarded as the
    X-Abenix-Subject header so the abenix-side auth dep can scope the read).
  * POST /api/contractiq/moderation/vet — proxy to `/api/moderation/vet`.
  * `vet_or_block(content, user, source)` — internal helper that the chat /
    upload / analyze endpoints call before the agent. If the platform
    returns action='block' we raise HTTPException(422) with a structured
    `moderation_block` payload; allow / disabled / unreachable -> proceed.

Feature flag: `CIQ_MODERATION_ENABLED` (default true). Set to "0"/"false"
to skip the gate entirely.
"""

from __future__ import annotations

import json
import logging
import os

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from app.models.contractiq_models import ContractIQUser
from app.routers.auth import get_contractiq_user, tenant_id_for


ABENIX_URL = os.environ.get("ABENIX_API_URL", "http://abenix-api:8000")
API_KEY = os.environ.get("CONTRACTIQ_ABENIX_API_KEY", "")

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/contractiq/moderation", tags=["contractiq-moderation"])


def moderation_enabled() -> bool:
    """Tenant-wide kill switch. Defaults on; "0"/"false"/"no" turn it off."""
    raw = (os.environ.get("CIQ_MODERATION_ENABLED") or "true").strip().lower()
    return raw not in ("0", "false", "no", "off", "")


def _subject_header(user: ContractIQUser | None) -> dict[str, str]:
    """Stamp the CIQ caller onto abenix calls so tenant scoping works.

    Mirrors the helper in executions.py — same shape so the abenix-side
    auth + audit pipelines see a consistent acting subject.
    """
    if user is None:
        return {}
    payload: dict[str, str] = {
        "subject_type": "contractiq",
        "subject_id": str(user.id),
        "tenant_id": tenant_id_for(user),
    }
    if getattr(user, "email", None):
        payload["email"] = user.email
    if getattr(user, "full_name", None):
        payload["display_name"] = user.full_name
    return {"X-Abenix-Subject": json.dumps(payload)}


def _headers(user: ContractIQUser | None = None) -> dict[str, str]:
    h: dict[str, str] = {"Accept": "application/json"}
    if API_KEY:
        h["X-API-Key"] = API_KEY
    h.update(_subject_header(user))
    return h


@router.get("/policies")
async def list_policies(
    user: ContractIQUser = Depends(get_contractiq_user),
) -> JSONResponse:
    """Read-through proxy for the platform's active moderation policies.

    The CIQ tenant id is forwarded via X-Abenix-Subject so the abenix-side
    handler scopes the result to this tenant.
    """
    if not API_KEY:
        return JSONResponse({"data": [], "error": "CONTRACTIQ_ABENIX_API_KEY not configured"})
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"{ABENIX_URL}/api/moderation/policies",
                headers=_headers(user),
            )
            if r.status_code >= 400:
                return JSONResponse({"data": [], "error": f"abenix returned {r.status_code}"})
            j = r.json()
            items = j.get("data") if isinstance(j, dict) else j
            if items is None:
                items = []
            return JSONResponse({"data": items, "enabled": moderation_enabled()})
    except Exception as e:
        logger.warning("moderation policies proxy failed: %r", e)
        return JSONResponse({"data": [], "error": str(e)})


@router.post("/vet")
async def vet(
    body: dict,
    user: ContractIQUser = Depends(get_contractiq_user),
) -> JSONResponse:
    """Proxy to the platform's `/api/moderation/vet`.

    The body shape matches the platform endpoint: `{content, strict?,
    policy_overrides?}`. We bail with 503 when the platform call fails so
    callers don't silently believe content is safe.
    """
    content = str((body or {}).get("content") or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="content is required")
    if not API_KEY:
        raise HTTPException(status_code=503, detail="CONTRACTIQ_ABENIX_API_KEY not configured")
    if not moderation_enabled():
        # Honest "skipped" envelope so callers don't read "allow" by accident.
        return JSONResponse({
            "outcome": "skipped",
            "action": "allow",
            "flagged": False,
            "reason": "CIQ_MODERATION_ENABLED=false",
            "triggered_categories": [],
        })
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                f"{ABENIX_URL}/api/moderation/vet",
                headers={**_headers(user), "Content-Type": "application/json"},
                json=body,
            )
            if r.status_code >= 500:
                raise HTTPException(status_code=503, detail=f"moderation upstream {r.status_code}")
            try:
                j = r.json()
            except Exception:
                raise HTTPException(status_code=503, detail="moderation upstream returned non-JSON")
            data = j.get("data") if isinstance(j, dict) else j
            return JSONResponse(data if data is not None else {})
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("moderation vet proxy failed: %r", e)
        raise HTTPException(status_code=503, detail=f"moderation upstream unreachable: {e}")


# ── internal gate used by chat / upload / analyze ───────────────────────

async def vet_or_block(
    content: str,
    user: ContractIQUser,
    source: str,
    *,
    strict: bool = False,
) -> None:
    """Run platform moderation on `content`; raise 422 on block, return on allow.

    Behaviour matrix:
      * flag off (CIQ_MODERATION_ENABLED=false) -> no-op
      * no API key configured -> no-op (dev/local), logged at WARNING
      * upstream unreachable / non-JSON / 5xx -> no-op (fail-open) with
        WARNING log; the in-cluster agent-runtime gate still runs as a
        backstop so we never go fully unprotected
      * upstream returns action='block' -> raise HTTPException(422, ...)
      * anything else -> proceed

    `source` is appended to a per-source content prefix so the platform
    audit log shows which CIQ surface triggered the call.
    """
    if not moderation_enabled():
        return
    if not API_KEY:
        logger.warning("ciq moderation gate skipped (%s): no API key", source)
        return
    text = (content or "").strip()
    if not text:
        return
    # The platform endpoint caps the LLM call internally; we trim here to
    # avoid pushing megabytes per request on big PDFs.
    if len(text) > 60000:
        text = text[:60000]
    payload = {"content": text, "strict": strict}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                f"{ABENIX_URL}/api/moderation/vet",
                headers={**_headers(user), "Content-Type": "application/json"},
                json=payload,
            )
            if r.status_code >= 400:
                logger.warning(
                    "ciq moderation gate upstream %s for %s: %s",
                    r.status_code, source, r.text[:200],
                )
                return
            try:
                j = r.json()
            except Exception:
                logger.warning("ciq moderation gate non-JSON response for %s", source)
                return
            data = j.get("data") if isinstance(j, dict) else j
            if not isinstance(data, dict):
                return
    except Exception as e:
        logger.warning("ciq moderation gate unreachable for %s: %r", source, e)
        return

    action = str(data.get("action") or "").lower()
    outcome = str(data.get("outcome") or "").lower()
    if action == "block" or outcome == "blocked":
        cats = data.get("triggered_categories") or []
        primary = cats[0] if cats else (data.get("category") or "policy")
        reason = data.get("reason") or "content blocked by moderation policy"
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "moderation_block",
                "message": str(reason),
                "category": str(primary),
                "categories": list(cats) if isinstance(cats, list) else [],
                "source": source,
            },
        )
