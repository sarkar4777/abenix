# SSO / OIDC sign-in for Google, GitHub, Microsoft. Wire flow:
#   GET /start  -> sign state JWT, 302 to provider's authorize URL
#   GET /callback -> verify state, exchange code, upsert user, issue
#                    our JWTs, 302 to ${WEB_BASE_URL}/auth/callback#tok=...
#
# Env vars needed:
#   GOOGLE_OIDC_CLIENT_ID, GOOGLE_OIDC_CLIENT_SECRET
#   GITHUB_OAUTH_CLIENT_ID, GITHUB_OAUTH_CLIENT_SECRET
#   MICROSOFT_OIDC_CLIENT_ID, MICROSOFT_OIDC_CLIENT_SECRET
#   MICROSOFT_OIDC_TENANT (default "common")
#   PUBLIC_API_BASE_URL (where provider redirects back)
#   WEB_BASE_URL (SPA root for final hop)
# A provider with missing creds returns 503 on /start; /providers lists
# only the configured ones so the SPA renders the right buttons.

from __future__ import annotations

import os
import secrets
import sys
import time
import urllib.parse
import uuid
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import log_action
from app.core.deps import get_db
from app.core.responses import error, success
from app.core.security import (
    create_access_token,
    create_refresh_token,
    verify_token,
)
import jwt

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.moderation_policy import ModerationAction, ModerationPolicy
from models.tenant import Tenant
from models.user import User, UserRole

router = APIRouter(prefix="/api/auth/oidc", tags=["auth"])


def _env(name: str) -> str | None:
    v = os.environ.get(name, "").strip()
    return v or None


def _api_base() -> str:
    return os.environ.get("PUBLIC_API_BASE_URL", "http://localhost:8000").rstrip("/")


def _web_base() -> str:
    return os.environ.get("WEB_BASE_URL", "http://localhost:3000").rstrip("/")


def _state_secret() -> str:
    # Reuse JWT_SECRET_KEY so we don't need a separate rotation surface.
    return os.environ.get("JWT_SECRET_KEY", "dev-secret-do-not-use-in-prod")


def _redirect_uri(provider: str) -> str:
    return f"{_api_base()}/api/auth/oidc/{provider}/callback"


PROVIDERS = ("google", "github", "microsoft")


def _provider_configured(provider: str) -> bool:
    if provider == "google":
        return bool(_env("GOOGLE_OIDC_CLIENT_ID") and _env("GOOGLE_OIDC_CLIENT_SECRET"))
    if provider == "github":
        return bool(
            _env("GITHUB_OAUTH_CLIENT_ID") and _env("GITHUB_OAUTH_CLIENT_SECRET")
        )
    if provider == "microsoft":
        return bool(
            _env("MICROSOFT_OIDC_CLIENT_ID") and _env("MICROSOFT_OIDC_CLIENT_SECRET")
        )
    return False


def _sign_state(provider: str, return_to: str) -> str:
    payload = {
        "provider": provider,
        "return_to": return_to,
        "nonce": secrets.token_urlsafe(16),
        "exp": int(time.time()) + 600,  # 10-minute window
        "iat": int(time.time()),
        "type": "oidc_state",
    }
    return jwt.encode(payload, _state_secret(), algorithm="HS256")


def _verify_state(state: str, provider: str) -> dict[str, Any] | None:
    try:
        payload = jwt.decode(state, _state_secret(), algorithms=["HS256"])
    except Exception:
        return None
    if payload.get("type") != "oidc_state":
        return None
    if payload.get("provider") != provider:
        return None
    return payload


@router.get("/providers")
async def list_providers() -> Any:
    """Which SSO buttons the login page should render."""
    return success(
        {
            "providers": [p for p in PROVIDERS if _provider_configured(p)],
        }
    )


@router.get("/{provider}/start")
async def start(provider: str, request: Request) -> Any:
    if provider not in PROVIDERS:
        return error(f"Unknown provider: {provider}", 404)
    if not _provider_configured(provider):
        return error(f"{provider} SSO is not configured on this deployment", 503)

    raw_return_to = request.query_params.get("return_to", "/dashboard") or "/dashboard"
    # Only relative paths under the SPA — never an absolute URL the
    # attacker could point at their own host.
    return_to = raw_return_to if raw_return_to.startswith("/") else "/dashboard"
    state = _sign_state(provider, return_to)
    redirect_uri = _redirect_uri(provider)

    if provider == "google":
        params = {
            "client_id": _env("GOOGLE_OIDC_CLIENT_ID"),
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "access_type": "offline",
            "prompt": "select_account",
        }
        url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(
            params
        )
        return RedirectResponse(url=url)

    if provider == "github":
        params = {
            "client_id": _env("GITHUB_OAUTH_CLIENT_ID"),
            "redirect_uri": redirect_uri,
            "scope": "read:user user:email",
            "state": state,
        }
        url = "https://github.com/login/oauth/authorize?" + urllib.parse.urlencode(
            params
        )
        return RedirectResponse(url=url)

    if provider == "microsoft":
        tenant = _env("MICROSOFT_OIDC_TENANT") or "common"
        params = {
            "client_id": _env("MICROSOFT_OIDC_CLIENT_ID"),
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile offline_access",
            "state": state,
            "response_mode": "query",
        }
        url = (
            f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize?"
            + urllib.parse.urlencode(params)
        )
        return RedirectResponse(url=url)

    return error(f"Unknown provider: {provider}", 404)


async def _exchange_google(code: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15) as client:
        token_resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": _env("GOOGLE_OIDC_CLIENT_ID"),
                "client_secret": _env("GOOGLE_OIDC_CLIENT_SECRET"),
                "redirect_uri": _redirect_uri("google"),
                "grant_type": "authorization_code",
            },
        )
        token_resp.raise_for_status()
        access_token = token_resp.json().get("access_token")
        user_resp = await client.get(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        user_resp.raise_for_status()
        u = user_resp.json()
        return {
            "external_id": u.get("sub"),
            "email": (u.get("email") or "").lower(),
            "full_name": u.get("name") or u.get("email") or "Google user",
            "avatar_url": u.get("picture"),
        }


async def _exchange_github(code: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15) as client:
        token_resp = await client.post(
            "https://github.com/login/oauth/access_token",
            data={
                "code": code,
                "client_id": _env("GITHUB_OAUTH_CLIENT_ID"),
                "client_secret": _env("GITHUB_OAUTH_CLIENT_SECRET"),
                "redirect_uri": _redirect_uri("github"),
            },
            headers={"Accept": "application/json"},
        )
        token_resp.raise_for_status()
        access_token = token_resp.json().get("access_token")
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github+json",
        }
        user_resp = await client.get("https://api.github.com/user", headers=headers)
        user_resp.raise_for_status()
        u = user_resp.json()
        email = u.get("email")
        if not email:
            emails_resp = await client.get(
                "https://api.github.com/user/emails", headers=headers
            )
            emails_resp.raise_for_status()
            emails = emails_resp.json() or []
            primary = next(
                (e for e in emails if e.get("primary") and e.get("verified")),
                next((e for e in emails if e.get("verified")), None),
            )
            email = primary.get("email") if primary else None
        if not email:
            raise ValueError(
                "GitHub account has no verified email; cannot create Abenix account"
            )
        return {
            "external_id": str(u.get("id")),
            "email": email.lower(),
            "full_name": u.get("name") or u.get("login") or "GitHub user",
            "avatar_url": u.get("avatar_url"),
        }


async def _exchange_microsoft(code: str) -> dict[str, Any]:
    tenant = _env("MICROSOFT_OIDC_TENANT") or "common"
    async with httpx.AsyncClient(timeout=15) as client:
        token_resp = await client.post(
            f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
            data={
                "code": code,
                "client_id": _env("MICROSOFT_OIDC_CLIENT_ID"),
                "client_secret": _env("MICROSOFT_OIDC_CLIENT_SECRET"),
                "redirect_uri": _redirect_uri("microsoft"),
                "grant_type": "authorization_code",
                "scope": "openid email profile",
            },
        )
        token_resp.raise_for_status()
        access_token = token_resp.json().get("access_token")
        user_resp = await client.get(
            "https://graph.microsoft.com/v1.0/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        user_resp.raise_for_status()
        u = user_resp.json()
        email = (u.get("mail") or u.get("userPrincipalName") or "").lower()
        if not email:
            raise ValueError(
                "Microsoft account exposed no email; cannot create Abenix account"
            )
        return {
            "external_id": u.get("id"),
            "email": email,
            "full_name": u.get("displayName") or email,
            "avatar_url": None,
        }


def _slugify(text: str) -> str:
    import re

    slug = text.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-") or "user"


async def _upsert_user(
    db: AsyncSession,
    provider: str,
    profile: dict[str, Any],
    request: Request,
) -> User:
    # Resolve in priority: (provider, external_id) → email → new user.
    found = await db.execute(
        select(User).where(
            User.auth_provider == provider,
            User.external_id == profile["external_id"],
        )
    )
    user = found.scalar_one_or_none()
    if user:
        # Refresh display fields cheaply on every login.
        if profile.get("full_name"):
            user.full_name = profile["full_name"]
        if profile.get("avatar_url"):
            user.avatar_url = profile["avatar_url"]
        await db.commit()
        await db.refresh(user)
        return user

    by_email = await db.execute(select(User).where(User.email == profile["email"]))
    user = by_email.scalar_one_or_none()
    if user:
        # Existing local user adopts the SSO link — preserves password
        # for fallback so both flows continue to work.
        user.auth_provider = provider
        user.external_id = profile["external_id"]
        if profile.get("avatar_url") and not user.avatar_url:
            user.avatar_url = profile["avatar_url"]
        await db.commit()
        await db.refresh(user)
        await log_action(
            db,
            user.tenant_id,
            user.id,
            "user.sso_linked",
            {"provider": provider},
            request,
        )
        await db.commit()
        return user

    # Fresh sign-up via SSO: provision a tenant + admin user + default
    # moderation policy, mirroring /api/auth/register.
    tenant = Tenant(
        id=uuid.uuid4(),
        name=f"{profile['full_name']}'s Workspace",
        slug=_slugify(f"{profile['full_name']}-{uuid.uuid4().hex[:6]}"),
    )
    db.add(tenant)
    await db.flush()

    user = User(
        id=uuid.uuid4(),
        email=profile["email"],
        password_hash=None,
        full_name=profile["full_name"],
        avatar_url=profile.get("avatar_url"),
        role=UserRole.ADMIN,
        tenant_id=tenant.id,
        auth_provider=provider,
        external_id=profile["external_id"],
    )
    db.add(user)
    await db.flush()

    policy = ModerationPolicy(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="Default Policy",
        description="Auto-seeded on tenant creation. Edit at /moderation.",
        is_active=True,
        pre_llm=True,
        post_llm=True,
        on_tool_output=False,
        provider="openai",
        provider_model="omni-moderation-latest",
        thresholds={},
        default_threshold=0.5,
        category_actions={},
        default_action=ModerationAction.BLOCK,
        custom_patterns=[],
        redaction_mask="█████",
        # Not fail-closed by default. The seeded provider is OpenAI, and on a
        # deployment with no OpenAI credential every provider call errors —
        # fail_closed then escalated that to a hard block, so 100% of agent
        # requests were refused with no category to explain it. The custom
        # pattern checks (PII, secrets) need no provider and still apply.
        # Strict mode stays available as an explicit opt-in at /moderation.
        fail_closed=False,
        created_by=user.id,
    )
    db.add(policy)
    await db.commit()
    await db.refresh(user)

    await log_action(
        db,
        tenant.id,
        user.id,
        "user.registered_via_sso",
        {"email": user.email, "provider": provider},
        request,
    )
    await db.commit()
    return user


@router.get("/{provider}/callback")
async def callback(
    provider: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Any:
    if provider not in PROVIDERS:
        return error(f"Unknown provider: {provider}", 404)
    if not _provider_configured(provider):
        return error(f"{provider} SSO is not configured on this deployment", 503)

    code = request.query_params.get("code")
    state = request.query_params.get("state")
    provider_error = request.query_params.get("error")
    if provider_error:
        return error(f"{provider} authorization denied: {provider_error}", 400)
    if not code or not state:
        return error("Missing code or state", 400)

    state_payload = _verify_state(state, provider)
    if not state_payload:
        return error("Invalid or expired OIDC state", 400)
    return_to = state_payload.get("return_to", "/dashboard")

    try:
        if provider == "google":
            profile = await _exchange_google(code)
        elif provider == "github":
            profile = await _exchange_github(code)
        elif provider == "microsoft":
            profile = await _exchange_microsoft(code)
        else:
            return error(f"Unknown provider: {provider}", 404)
    except httpx.HTTPError as e:
        return error(f"Token exchange with {provider} failed: {e}", 502)
    except ValueError as e:
        return error(str(e), 400)

    if not profile.get("email") or not profile.get("external_id"):
        return error(
            f"{provider} returned an incomplete profile (missing email or subject)",
            502,
        )

    user = await _upsert_user(db, provider, profile, request)
    if not user.is_active:
        return error("Account is disabled", 403)

    await log_action(
        db, user.tenant_id, user.id, "user.login_sso", {"provider": provider}, request
    )
    await db.commit()

    access = create_access_token(user.id, user.tenant_id, user.role.value)
    refresh = create_refresh_token(user.id)

    spa_target = (
        f"{_web_base()}/auth/callback"
        f"#access_token={urllib.parse.quote(access)}"
        f"&refresh_token={urllib.parse.quote(refresh)}"
        f"&return_to={urllib.parse.quote(return_to)}"
    )
    return RedirectResponse(url=spa_target)


# Re-export for tests
__all__ = ["router", "verify_token", "_sign_state", "_verify_state"]
