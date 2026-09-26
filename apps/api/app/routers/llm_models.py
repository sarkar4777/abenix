from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.responses import success

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packages" / "db"))
from models.llm_pricing import LLMModelPricing, ModelAvailability  # type: ignore  # noqa: E402
from models.user import User  # type: ignore  # noqa: E402

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/llm-models", tags=["llm-models"])
# Sibling router so the provider-probe lives at /api/llm/available-providers
# (the dropdown's data layer asks both /api/llm-models and /api/llm/available-providers).
provider_router = APIRouter(prefix="/api/llm", tags=["llm-models"])


# Provider env-var map. We probe each one and treat anything falsy, "placeholder",
# or "dev" as not-configured so an unset deployment doesn't look healthy.
_PROVIDER_ENV: dict[str, tuple[str, ...]] = {
    "anthropic": ("ANTHROPIC_API_KEY",),
    "openai": ("OPENAI_API_KEY",),
    "google": ("GOOGLE_API_KEY", "GEMINI_API_KEY"),
    "azure": ("AZURE_OPENAI_API_KEY",),
    # A Claude subscription is credentialled by an OAuth token rather than
    # an API key, and can also be set from Admin -> LLM Settings.
    "claude_subscription": ("CLAUDE_SUBSCRIPTION_TOKEN", "ANTHROPIC_AUTH_TOKEN"),
}

_TRUTHY = {"1", "true", "yes", "on"}


async def _subscription_state(db: AsyncSession) -> dict[str, Any]:
    """Subscription mode as the pickers need to see it."""
    try:
        rows = (
            await db.execute(
                text(
                    "SELECT key, value FROM platform_settings "
                    "WHERE key LIKE 'llm.subscription.%'"
                )
            )
        ).all()
        stored = {str(k): str(v or "") for k, v in rows}
    except Exception as exc:
        logger.debug("subscription state probe skipped: %s", exc)
        stored = {}

    token = stored.get("llm.subscription.token", "").strip()
    if not token:
        for name in _PROVIDER_ENV["claude_subscription"]:
            val = os.environ.get(name, "")
            if _is_real_key(val):
                token = val.strip()
                break
    enabled = stored.get("llm.subscription.enabled", "false").strip().lower() in _TRUTHY
    exclusive = (
        stored.get("llm.subscription.exclusive", "true").strip().lower() in _TRUTHY
    )
    return {
        "enabled": enabled,
        "token_set": bool(token),
        "active": enabled and bool(token),
        "exclusive": exclusive,
        "default_model": stored.get("llm.subscription.default_model", "").strip()
        or "claude-opus-5",
    }


_PROVIDER_CACHE: dict[str, dict[str, Any]] = {}
_PROVIDER_CACHE_AT: float = 0.0
_PROVIDER_TTL = 60.0


def _is_real_key(val: str | None) -> bool:
    if not val:
        return False
    v = val.strip().lower()
    if not v:
        return False
    return v not in {"placeholder", "dev", "changeme", "none", "null"}


async def _probe_providers(db: AsyncSession) -> dict[str, dict[str, Any]]:
    """Return the configured/reason map for each provider. 60s cached."""
    global _PROVIDER_CACHE, _PROVIDER_CACHE_AT
    now = time.monotonic()
    if _PROVIDER_CACHE and (now - _PROVIDER_CACHE_AT) < _PROVIDER_TTL:
        return _PROVIDER_CACHE

    # Pull any provider keys mirrored into platform_settings (e.g.
    # `provider.openai.api_key`). Treat missing table / row as benign.
    db_keys: dict[str, str] = {}
    try:
        rows = (
            await db.execute(
                text(
                    "SELECT key, value FROM platform_settings "
                    "WHERE key LIKE 'provider.%.api_key' OR category = 'secrets'"
                )
            )
        ).all()
        for k, v in rows:
            db_keys[str(k)] = str(v or "")
    except Exception as exc:
        logger.debug("platform_settings probe skipped: %s", exc)

    # The subscription token lives under its own settings key, not the
    # `provider.<name>.api_key` convention the API-key providers use.
    sub_token = ""
    try:
        sub_token = str(
            (
                await db.execute(
                    text(
                        "SELECT value FROM platform_settings "
                        "WHERE key = 'llm.subscription.token'"
                    )
                )
            ).scalar_one_or_none()
            or ""
        ).strip()
    except Exception as exc:
        logger.debug("subscription token probe skipped: %s", exc)

    result: dict[str, dict[str, Any]] = {}
    for provider, env_names in _PROVIDER_ENV.items():
        env_val = ""
        chosen_env = env_names[0]
        for name in env_names:
            v = os.environ.get(name, "")
            if _is_real_key(v):
                env_val = v
                chosen_env = name
                break
        if provider == "claude_subscription":
            db_val = sub_token
            missing_reason = "no subscription token — paste one in Admin → LLM Settings"
        else:
            db_val = db_keys.get(f"provider.{provider}.api_key", "")
            missing_reason = f"{chosen_env} not set"
        if _is_real_key(env_val) or _is_real_key(db_val):
            result[provider] = {"configured": True, "reason": None}
        else:
            result[provider] = {
                "configured": False,
                "reason": missing_reason,
            }

    _PROVIDER_CACHE = result
    _PROVIDER_CACHE_AT = now
    return result


def _provider_from_model(model: str, declared: str | None) -> str:
    if declared:
        return declared.lower()
    m = (model or "").lower()
    if m.startswith("azure-"):
        return "azure"
    if m.startswith("claude"):
        return "anthropic"
    if m.startswith("gpt"):
        return "openai"
    if m.startswith("gemini"):
        return "google"
    return "other"


def _display(
    row: LLMModelPricing,
    avail: ModelAvailability | None,
    providers: dict[str, dict[str, Any]] | None = None,
    subscription: dict[str, Any] | None = None,
) -> dict[str, Any]:
    label = row.display_name
    if not label:
        m = row.model
        if m.startswith("azure-"):
            label = "Azure " + m[len("azure-") :].upper().replace("-", " ")
        elif m.startswith("claude"):
            label = m.replace("claude-", "Claude ").replace("-", " ").title()
        elif m.startswith("gpt"):
            label = m.upper()
        elif m.startswith("gemini"):
            label = "Gemini " + m.replace("gemini-", "").title()
        else:
            label = m
    status = "available"
    if avail is not None:
        status = avail.status or "available"
    prov_name = _provider_from_model(row.model, row.provider)
    prov_info = (providers or {}).get(prov_name) or {}
    provider_available = bool(prov_info.get("configured", True))

    # When subscription mode is live, say so per-model: Claude models run on
    # it directly, and in exclusive mode everything else is remapped onto the
    # configured Claude model. Either way the call costs nothing extra.
    sub = subscription or {}
    served_by_subscription = False
    remapped_to: str | None = None
    if sub.get("active"):
        if row.model.lower().startswith("claude"):
            served_by_subscription = True
        elif sub.get("exclusive"):
            served_by_subscription = True
            remapped_to = sub.get("default_model")
    if served_by_subscription:
        provider_available = True

    return {
        "value": row.model,
        "label": label,
        "provider": row.provider,
        "served_by": "claude_subscription" if served_by_subscription else prov_name,
        "subscription_served": served_by_subscription,
        "subscription_remapped_to": remapped_to,
        "is_deprecated": bool(row.is_deprecated),
        "deprecated_at": row.deprecated_at.isoformat() if row.deprecated_at else None,
        "migration_hint": row.migration_hint,
        "input_per_m": float(row.input_per_m),
        "output_per_m": float(row.output_per_m),
        "capabilities": row.capabilities or {},
        "fallback_to": list(row.fallback_to or []),
        "status": status,
        "last_checked_at": (
            avail.last_checked_at.isoformat()
            if avail and avail.last_checked_at
            else None
        ),
        "last_error": (avail.last_error if avail else None),
        "provider_available": provider_available,
        "provider_unavailable_reason": prov_info.get("reason"),
    }


@router.get("")
async def list_models(
    include_deprecated: bool = False,
    include_unavailable: bool = True,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Public-to-tenant endpoint feeding every model dropdown."""
    rows = (
        await db.execute(
            text(
                """
                SELECT DISTINCT ON (model) id
                FROM llm_model_pricing
                WHERE is_active = TRUE
                ORDER BY model, effective_from DESC
                """
            )
        )
    ).all()
    ids = [r[0] for r in rows]
    pricing_rows = (
        (
            await db.execute(
                select(LLMModelPricing)
                .where(LLMModelPricing.id.in_(ids))
                .order_by(LLMModelPricing.provider.asc(), LLMModelPricing.model.asc())
            )
        )
        .scalars()
        .all()
    )
    avail_rows = (await db.execute(select(ModelAvailability))).scalars().all()
    by_model = {a.model: a for a in avail_rows}
    providers = await _probe_providers(db)
    subscription = await _subscription_state(db)

    items: list[dict[str, Any]] = []
    for row in pricing_rows:
        if not include_deprecated and row.is_deprecated:
            continue
        avail = by_model.get(row.model)
        if not include_unavailable and avail and avail.status != "available":
            continue
        items.append(_display(row, avail, providers, subscription))

    return success({"models": items, "subscription": subscription})


@provider_router.get("/available-providers")
async def list_available_providers(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Per-provider configured/reason map for the model picker to grey-out missing providers."""
    providers = await _probe_providers(db)
    return success(providers)


@router.get("/resolve")
async def resolve_model(
    model: str,
    needs_tools: bool = False,
    needs_vision: bool = False,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Return what the resolver would pick if a run for `model` started right now."""
    sys.path.insert(
        0, str(Path(__file__).resolve().parents[4] / "apps" / "agent-runtime")
    )
    try:
        from engine.model_resolver import resolve as _resolve  # type: ignore

        required: dict[str, bool] = {}
        if needs_tools:
            required["tools"] = True
        if needs_vision:
            required["vision"] = True
        decision = _resolve(model, required_capabilities=required)
        avail = (
            await db.execute(
                select(ModelAvailability).where(ModelAvailability.model == model)
            )
        ).scalar_one_or_none()
        pricing = (
            await db.execute(
                select(LLMModelPricing)
                .where(
                    LLMModelPricing.model == model, LLMModelPricing.is_active.is_(True)
                )
                .order_by(LLMModelPricing.effective_from.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return success(
            {
                "requested": decision.requested,
                "effective": decision.effective,
                "chain": decision.chain,
                "reason": decision.reason,
                "swap": decision.effective != decision.requested,
                "requested_status": (avail.status if avail else "available"),
                "requested_is_deprecated": (
                    bool(pricing.is_deprecated) if pricing else False
                ),
                "requested_last_error": (avail.last_error if avail else None),
                "migration_hint": (pricing.migration_hint if pricing else None),
            }
        )
    except Exception as exc:
        logger.warning("resolve_model failed: %s", exc)
        return success(
            {
                "requested": model,
                "effective": model,
                "chain": [model],
                "reason": "resolver_unavailable",
                "swap": False,
                "requested_status": "available",
                "requested_is_deprecated": False,
                "requested_last_error": None,
                "migration_hint": None,
            }
        )


@router.post("/ping-now")
async def ping_now(
    user: User = Depends(get_current_user),
) -> JSONResponse:
    if str(getattr(user.role, "value", user.role) or "").lower() != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    from app.services.model_availability import run_pings

    res = await run_pings()
    return success(res)


@router.post("/clear-stale")
async def clear_stale(
    body: dict[str, Any] | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Force-clear sticky 'unavailable' markers so the next request re-probes.

    Body is optional. Supported keys:
      - models: list[str]  — only clear these (default: all unavailable rows)
      - reping: bool       — also run an immediate prober pass after clearing
    """
    if str(getattr(user.role, "value", user.role) or "").lower() != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    body = body or {}
    models = [str(m).strip() for m in (body.get("models") or []) if str(m).strip()]
    reping = bool(body.get("reping", False))

    from datetime import datetime as _dt, timezone as _tz

    now = _dt.now(_tz.utc)

    # Snapshot the rows we're about to flip so we can emit transition events.
    if models:
        rows = (
            (
                await db.execute(
                    select(ModelAvailability).where(
                        ModelAvailability.model.in_(models),
                        ModelAvailability.status == "unavailable",
                    )
                )
            )
            .scalars()
            .all()
        )
    else:
        rows = (
            (
                await db.execute(
                    select(ModelAvailability).where(
                        ModelAvailability.status == "unavailable"
                    )
                )
            )
            .scalars()
            .all()
        )

    cleared: list[str] = []
    for row in rows:
        await db.execute(
            text(
                """
                INSERT INTO model_availability_events (model, from_status, to_status, error)
                VALUES (:m, :f, :t, :e)
                """
            ),
            {
                "m": row.model,
                "f": row.status,
                "t": "available",
                "e": "admin_clear_stale",
            },
        )
        row.status = "available"
        row.last_error = None
        row.consecutive_failures = 0
        row.status_since = now
        row.last_checked_at = now
        cleared.append(row.model)
    await db.commit()

    # Invalidate the resolver cache so the next route() call sees the cleared rows.
    try:
        sys.path.insert(
            0, str(Path(__file__).resolve().parents[4] / "apps" / "agent-runtime")
        )
        from engine.model_resolver import invalidate_cache  # type: ignore

        invalidate_cache()
    except Exception as exc:
        logger.debug("invalidate_cache skipped: %s", exc)

    reping_result: dict[str, Any] | None = None
    if reping:
        try:
            from app.services.model_availability import run_pings

            reping_result = await run_pings()
        except Exception as exc:
            logger.warning("clear-stale reping failed: %s", exc)
            reping_result = {"error": str(exc)[:512]}

    return success({"cleared": cleared, "count": len(cleared), "reping": reping_result})
