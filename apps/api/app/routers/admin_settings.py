"""Admin-only platform settings — which LLM powers each built-in"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.platform_settings import DEFAULTS, SECRET_KEYS, invalidate, mask
from app.core.responses import error, success

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packages" / "db"))
from models.user import User  # type: ignore

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin/settings", tags=["admin-settings"])


AVAILABLE_MODELS: list[dict[str, Any]] = [
    # Anthropic — current generation. Served either by an ANTHROPIC_API_KEY
    # or by a Claude Pro/Max subscription, depending on what is configured.
    {
        "id": "claude-opus-5",
        "provider": "anthropic",
        "label": "Claude Opus 5",
        "family": "claude-5",
        "capabilities": ["text", "vision", "tools", "reasoning"],
        "subscription_eligible": True,
    },
    {
        "id": "claude-sonnet-5",
        "provider": "anthropic",
        "label": "Claude Sonnet 5",
        "family": "claude-5",
        "capabilities": ["text", "vision", "tools", "reasoning"],
        "subscription_eligible": True,
    },
    {
        "id": "claude-haiku-4-5",
        "provider": "anthropic",
        "label": "Claude Haiku 4.5",
        "family": "claude-4",
        "capabilities": ["text", "vision", "tools"],
        "subscription_eligible": True,
    },
    # Anthropic
    {
        "id": "claude-sonnet-4-5-20250929",
        "provider": "anthropic",
        "label": "Claude Sonnet 4.5",
        "family": "claude-4",
        "capabilities": ["text", "vision", "tools", "reasoning"],
    },
    {
        "id": "claude-opus-4-5-20250929",
        "provider": "anthropic",
        "label": "Claude Opus 4.5",
        "family": "claude-4",
        "capabilities": ["text", "vision", "tools", "reasoning"],
    },
    {
        "id": "claude-haiku-4-5-20251001",
        "provider": "anthropic",
        "label": "Claude Haiku 4.5",
        "family": "claude-4",
        "capabilities": ["text", "vision", "tools"],
    },
    # Google
    {
        "id": "gemini-2.0-flash",
        "provider": "google",
        "label": "Gemini 2.0 Flash",
        "family": "gemini-2",
        "capabilities": ["text", "vision", "tools"],
    },
    {
        "id": "gemini-2.0-flash-exp",
        "provider": "google",
        "label": "Gemini 2.0 Flash (exp)",
        "family": "gemini-2",
        "capabilities": ["text", "vision", "tools"],
    },
    {
        "id": "gemini-2.5-pro",
        "provider": "google",
        "label": "Gemini 2.5 Pro",
        "family": "gemini-2",
        "capabilities": ["text", "vision", "tools", "reasoning"],
    },
    {
        "id": "gemini-2.5-flash",
        "provider": "google",
        "label": "Gemini 2.5 Flash",
        "family": "gemini-2",
        "capabilities": ["text", "vision", "tools"],
    },
    # OpenAI
    {
        "id": "gpt-4o",
        "provider": "openai",
        "label": "GPT-4o",
        "family": "gpt-4",
        "capabilities": ["text", "vision", "tools"],
    },
    {
        "id": "gpt-4o-mini",
        "provider": "openai",
        "label": "GPT-4o mini",
        "family": "gpt-4",
        "capabilities": ["text", "vision", "tools"],
    },
    {
        "id": "gpt-4-turbo",
        "provider": "openai",
        "label": "GPT-4 Turbo",
        "family": "gpt-4",
        "capabilities": ["text", "vision", "tools"],
    },
    # Azure OpenAI deployments — same families as openai/* but billed + routed
    # through the customer's Azure tenant. Selectable wherever an openai model
    # is selectable.
    {
        "id": "azure-gpt-4o",
        "provider": "azure",
        "label": "Azure GPT-4o",
        "family": "gpt-4",
        "capabilities": ["text", "vision", "tools"],
    },
    {
        "id": "azure-gpt-4o-mini",
        "provider": "azure",
        "label": "Azure GPT-4o mini",
        "family": "gpt-4",
        "capabilities": ["text", "vision", "tools"],
    },
]


_SUBSCRIPTION_ENV = ("CLAUDE_SUBSCRIPTION_TOKEN", "ANTHROPIC_AUTH_TOKEN")
_TOKEN_PLACEHOLDERS = {"", "placeholder", "dev", "changeme", "none", "null"}


def _env_subscription_token() -> str:
    """Subscription token supplied by the environment (headless installs)."""
    import os

    for name in _SUBSCRIPTION_ENV:
        val = (os.environ.get(name) or "").strip()
        if val and val.lower() not in _TOKEN_PLACEHOLDERS:
            return val
    return ""


async def _subscription_token(db: AsyncSession) -> str:
    stored = (
        await db.execute(
            text("SELECT value FROM platform_settings WHERE key = :k"),
            {"k": "llm.subscription.token"},
        )
    ).scalar_one_or_none()
    return (stored or "").strip() or _env_subscription_token()


def _ensure_admin(user: User) -> None:
    role = getattr(user, "role", None)
    r = role.value if hasattr(role, "value") else str(role or "")
    if r.lower() != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")


@router.get("")
async def list_settings(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Return every known setting (with current value or default) grouped by category."""
    _ensure_admin(user)

    rows = (
        await db.execute(
            text(
                "SELECT key, value, category, description, updated_at FROM platform_settings"
            )
        )
    ).fetchall()
    # ISO-format the timestamp so the JSONResponse encoder is happy
    stored = {
        r[0]: {
            "value": r[1],
            "category": r[2],
            "description": r[3],
            "updated_at": r[4].isoformat() if r[4] is not None else None,
        }
        for r in rows
    }

    out: dict[str, list[dict]] = {}
    for key, meta in DEFAULTS.items():
        current = stored.get(key, {})
        raw = current.get("value") or meta["value"]
        item = {
            "key": key,
            "value": mask(key, raw),
            "default": "" if key in SECRET_KEYS else meta["value"],
            "category": meta["category"],
            "description": meta["description"],
            "updated_at": current.get("updated_at"),
            "is_default": not current.get("value")
            or current.get("value") == meta["value"],
            "is_secret": key in SECRET_KEYS,
            # "model" (a model id, rendered as a picker) or "int" (a numeric
            # limit, rendered as a number input with the bounds below).
            "kind": meta.get("kind", "model"),
        }
        if meta.get("kind") == "int":
            item["min"] = meta.get("min")
            item["max"] = meta.get("max")
        if key in SECRET_KEYS:
            item["is_set"] = bool((current.get("value") or "").strip())
        out.setdefault(meta["category"], []).append(item)
    return success({"categories": out, "models": AVAILABLE_MODELS})


@router.get("/models")
async def list_models(
    user: User = Depends(get_current_user),
    capability: str = "",
) -> JSONResponse:
    """Master model list for the platform."""
    _ensure_admin(user)
    models = AVAILABLE_MODELS
    if capability:
        models = [m for m in models if capability in (m.get("capabilities") or [])]
    return success({"models": models})


@router.get("/models/public")
async def list_models_public(
    user: User = Depends(get_current_user),
    capability: str = "",
) -> JSONResponse:
    """Same master list, available to ANY authenticated user. This is the"""
    models = AVAILABLE_MODELS
    if capability:
        models = [m for m in models if capability in (m.get("capabilities") or [])]
    return success({"models": models})


@router.patch("/{key}")
async def update_setting(
    key: str,
    body: dict = Body(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    _ensure_admin(user)
    if key not in DEFAULTS:
        return error(f"Unknown setting '{key}'", 400)
    value = body.get("value")
    if value is None or not isinstance(value, str):
        return error("'value' is required and must be a string", 400)
    # A secret may be cleared; every other setting needs a real value.
    if not value.strip() and key not in SECRET_KEYS:
        return error("'value' is required and must be a non-empty string", 400)
    value = value.strip()

    # Validate against the model catalogue for *.model settings
    if key.endswith(".model") and value not in {m["id"] for m in AVAILABLE_MODELS}:
        return error(f"Model '{value}' is not in the allowed list", 400)

    # Numeric settings are read on the execution hot path, so reject a bad
    # value here rather than letting every run silently fall back.
    if meta_kind := DEFAULTS[key].get("kind"):
        if meta_kind == "int":
            try:
                num = int(value)
            except ValueError:
                return error(f"'{key}' must be a whole number", 400)
            lo = DEFAULTS[key].get("min")
            hi = DEFAULTS[key].get("max")
            if isinstance(lo, int) and num < lo:
                return error(f"'{key}' must be at least {lo}", 400)
            if isinstance(hi, int) and num > hi:
                return error(f"'{key}' must be at most {hi}", 400)
            value = str(num)

    if key == "llm.subscription.enabled" and value.lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        stored_token = (
            await db.execute(
                text("SELECT value FROM platform_settings WHERE key = :k"),
                {"k": "llm.subscription.token"},
            )
        ).scalar_one_or_none()
        if not (stored_token or "").strip() and not _env_subscription_token():
            return error(
                "Paste a subscription token before enabling subscription mode", 400
            )

    meta = DEFAULTS[key]
    await db.execute(
        text(
            """
        INSERT INTO platform_settings (key, value, category, description, updated_by)
        VALUES (:key, :value, :cat, :desc, :uid)
        ON CONFLICT (key)
        DO UPDATE SET value = :value, category = :cat, description = :desc,
                      updated_by = :uid, updated_at = now()
        """
        ),
        {
            "key": key,
            "value": value,
            "cat": meta["category"],
            "desc": meta["description"],
            "uid": user.id,
        },
    )
    await db.commit()
    invalidate(key)

    # Never log a secret's value — only that it changed.
    logger.info(
        "[admin.settings] %s set %s=%s",
        user.email,
        key,
        "<redacted>" if key in SECRET_KEYS else value[:80],
    )
    if key.startswith("llm."):
        from app.services.model_availability import schedule_reprobe

        schedule_reprobe()
    return success({"key": key, "value": mask(key, value), "updated_by": str(user.id)})


@router.get("/subscription")
async def subscription_status(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Whether subscription mode is on, and what it will serve."""
    _ensure_admin(user)
    rows = (
        await db.execute(
            text(
                "SELECT key, value FROM platform_settings "
                "WHERE key LIKE 'llm.subscription.%'"
            )
        )
    ).fetchall()
    stored = {str(k): (v or "") for k, v in rows}
    token = await _subscription_token(db)
    from engine.claude_subscription import subscription_state

    state = subscription_state(stored, token or "")
    enabled = bool(state["enabled"])
    exclusive = bool(state["exclusive"])
    return success(
        {
            "enabled": enabled,
            "token_set": bool(token),
            "token_source": (
                "settings"
                if (stored.get("llm.subscription.token") or "").strip()
                else ("environment" if token else None)
            ),
            "token_masked": mask("llm.subscription.token", token),
            "default_model": state["default_model"],
            "exclusive": exclusive,
            "active": enabled and bool(token),
            "billing": "flat-rate subscription — LLM calls record tokens at $0 marginal cost",
        }
    )


@router.post("/subscription/verify")
async def verify_subscription(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Make one real, minimal call with the stored token to prove it works."""
    _ensure_admin(user)
    token = await _subscription_token(db)
    if not token:
        return error("No subscription token configured", 400)

    model = (
        (
            await db.execute(
                text("SELECT value FROM platform_settings WHERE key = :k"),
                {"k": "llm.subscription.default_model"},
            )
        ).scalar_one_or_none()
        or DEFAULTS["llm.subscription.default_model"]["value"]
    ).strip()

    import anthropic

    client = anthropic.AsyncAnthropic(
        auth_token=token,
        default_headers={"anthropic-beta": "oauth-2025-04-20"},
    )
    try:
        resp = await client.messages.create(
            model=model,
            max_tokens=16,
            messages=[{"role": "user", "content": "Reply with the word ok."}],
        )
        text_out = "".join(
            b.text for b in resp.content if getattr(b, "type", "") == "text"
        )
        from app.services.model_availability import schedule_reprobe

        schedule_reprobe()
        return success(
            {
                "ok": True,
                "model": resp.model,
                "reply": text_out.strip()[:64],
                "input_tokens": resp.usage.input_tokens,
                "output_tokens": resp.usage.output_tokens,
            }
        )
    except anthropic.AuthenticationError as exc:
        return error(f"Token rejected: {exc.message}", 400)
    except anthropic.PermissionDeniedError as exc:
        return error(f"Token lacks access to {model}: {exc.message}", 400)
    except anthropic.NotFoundError:
        return error(f"Model '{model}' not available on this subscription", 400)
    except anthropic.RateLimitError:
        return error("Subscription rate limit reached — try again shortly", 429)
    except anthropic.APIStatusError as exc:
        return error(f"Anthropic returned {exc.status_code}: {exc.message}", 502)
    except anthropic.APIConnectionError:
        return error("Could not reach the Anthropic API from this cluster", 502)
    finally:
        await client.close()


@router.post("/reset")
async def reset_settings(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    _ensure_admin(user)
    # only the keys this screen manages, credentials and feature switches live elsewhere
    await db.execute(
        text("DELETE FROM platform_settings WHERE key = ANY(:keys)"),
        {"keys": list(DEFAULTS)},
    )
    await db.commit()
    invalidate()
    logger.warning("[admin.settings] %s reset all settings to defaults", user.email)
    return success({"reset": True})
