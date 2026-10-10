"""Workspace single sign-on with any OpenID Connect provider, set up by a workspace admin.

  PUT  /api/settings/sso            admin saves issuer, client, email domains, default role
  POST /api/auth/sso/discover       sign-in page asks which workspace owns an email domain
  GET  /api/auth/sso/{slug}/start   302 to the provider
  GET  /api/auth/sso/{slug}/callback  code exchange, find or create the member, our tokens

OIDC_INTERNAL_URL_MAP ("public=internal,...") lets a dev cluster reach a provider the
browser sees on localhost by its service name. Without it the issuer must be public https.
"""

from __future__ import annotations

import base64
import json
import os
import re
import secrets
import sys
import time
import urllib.parse
import uuid
from pathlib import Path
from typing import Any

import httpx
import jwt
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core import crypto, sessions
from app.core.audit import log_action
from app.core.deps import get_current_user, get_db
from app.core.responses import error, success

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.tenant import Tenant
from models.user import User, UserRole

router = APIRouter(tags=["auth"])

ROLES = ("user", "creator", "admin")
_DOMAIN = re.compile(r"^(?=.{3,253}$)([a-z0-9-]+\.)+[a-z]{2,63}$")
STATE_MINUTES = 10
_discovery_cache: dict[str, tuple[float, dict[str, Any]]] = {}


class SsoConfigRequest(BaseModel):
    enabled: bool = True
    issuer: str
    client_id: str
    client_secret: str | None = None
    domains: list[str] = []
    default_role: str = "user"
    label: str = ""
    auto_create: bool = True


class DiscoverRequest(BaseModel):
    email: str


class SsoError(Exception):
    pass


def _url_map() -> list[tuple[str, str]]:
    out = []
    for pair in os.environ.get("OIDC_INTERNAL_URL_MAP", "").split(","):
        if "=" in pair:
            pub, internal = pair.split("=", 1)
            if pub.strip() and internal.strip():
                out.append((pub.strip().rstrip("/"), internal.strip().rstrip("/")))
    return out


def to_internal(url: str) -> str:
    for pub, internal in _url_map():
        if url == pub or url.startswith(pub + "/"):
            return internal + url[len(pub) :]
    return url


def to_public(url: str) -> str:
    for pub, internal in _url_map():
        if url == internal or url.startswith(internal + "/"):
            return pub + url[len(internal) :]
    return url


def _mapped(url: str) -> bool:
    return to_internal(url) != url


async def issuer_problem(issuer: str) -> str | None:
    u = urllib.parse.urlparse(issuer or "")
    if u.scheme not in ("http", "https") or not u.hostname:
        return "The issuer must be a full URL, for example https://login.example.com"
    if _mapped(issuer):
        # an operator named this provider in OIDC_INTERNAL_URL_MAP
        return None
    if u.scheme != "https":
        return "The issuer must use https://"
    from app.services.events import unsafe_target

    blocked = await unsafe_target(issuer)
    if blocked:
        return blocked.replace("webhooks", "single sign-on")
    return None


async def discover(issuer: str, *, fresh: bool = False) -> dict[str, Any]:
    """The provider's endpoints, browser-facing ones mapped to public URLs."""
    issuer = issuer.rstrip("/")
    hit = _discovery_cache.get(issuer)
    if hit and not fresh and time.monotonic() - hit[0] < 300:
        return hit[1]
    problem = await issuer_problem(issuer)
    if problem:
        raise SsoError(problem)
    url = to_internal(issuer) + "/.well-known/openid-configuration"
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=False) as c:
            r = await c.get(url)
    except httpx.HTTPError as e:
        raise SsoError(f"The provider did not answer at {issuer}: {e}") from e
    if r.status_code != 200:
        raise SsoError(
            f"The provider answered {r.status_code} for its discovery document. Check the issuer URL."
        )
    try:
        doc = r.json()
    except ValueError as e:
        raise SsoError("The provider's discovery document is not JSON") from e
    for key in ("authorization_endpoint", "token_endpoint"):
        if not doc.get(key):
            raise SsoError(f"The provider's discovery document has no {key}")
    if to_public(str(doc.get("issuer") or "")).rstrip("/") != issuer:
        raise SsoError(
            f"The provider calls itself {to_public(str(doc.get('issuer')))}, not {issuer}. Use that as the issuer."
        )
    out = {
        "issuer": issuer,
        "authorization_endpoint": to_public(doc["authorization_endpoint"]),
        "token_endpoint": to_internal(to_public(doc["token_endpoint"])),
        "userinfo_endpoint": (
            to_internal(to_public(doc["userinfo_endpoint"]))
            if doc.get("userinfo_endpoint")
            else None
        ),
    }
    _discovery_cache[issuer] = (time.monotonic(), out)
    return out


def _cfg(tenant: Tenant | None) -> dict[str, Any]:
    return dict(((tenant.settings or {}) if tenant else {}).get("sso") or {})


def _api_base() -> str:
    return os.environ.get("PUBLIC_API_BASE_URL", "http://localhost:8000").rstrip("/")


def _web_base() -> str:
    return (
        os.environ.get("WEB_BASE_URL")
        or os.environ.get("FRONTEND_URL")
        or "http://localhost:3000"
    ).rstrip("/")


def redirect_uri(slug: str) -> str:
    return f"{_api_base()}/api/auth/sso/{slug}/callback"


def _public_cfg(tenant: Tenant) -> dict[str, Any]:
    c = _cfg(tenant)
    return {
        "configured": bool(c.get("issuer")),
        "enabled": bool(c.get("enabled")),
        "issuer": c.get("issuer") or "",
        "client_id": c.get("client_id") or "",
        "client_secret_set": bool(c.get("client_secret")),
        "domains": c.get("domains") or [],
        "default_role": c.get("default_role") or "user",
        "label": c.get("label") or "",
        "auto_create": c.get("auto_create", True) is not False,
        "redirect_uri": redirect_uri(tenant.slug),
        "start_url": f"{_api_base()}/api/auth/sso/{tenant.slug}/start",
    }


def clean_domains(raw: list[str]) -> tuple[list[str], str | None]:
    out: list[str] = []
    for d in raw or []:
        d = (d or "").strip().lower().lstrip("@")
        if not d:
            continue
        if not _DOMAIN.match(d):
            return (
                [],
                f"{d} is not an email domain. Use the part after @, like example.com",
            )
        if d not in out:
            out.append(d)
    return out, None


async def _tenants_with_sso(db: AsyncSession) -> list[Tenant]:
    rows = (
        (await db.execute(select(Tenant).where(Tenant.settings.has_key("sso"))))
        .scalars()
        .all()
    )
    return [t for t in rows if _cfg(t).get("issuer")]


def _admin(user: User) -> bool:
    return getattr(user.role, "value", user.role) == UserRole.ADMIN.value


@router.get("/api/settings/sso")
async def get_sso(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    if not _admin(user):
        return error("Only workspace admins can see single sign-on settings", 403)
    tenant = await db.get(Tenant, user.tenant_id)
    if tenant is None:
        return error("Workspace not found", 404)
    return success(_public_cfg(tenant))


@router.put("/api/settings/sso")
async def put_sso(
    body: SsoConfigRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if not _admin(user):
        return error("Only workspace admins can change single sign-on", 403)
    tenant = await db.get(Tenant, user.tenant_id)
    if tenant is None:
        return error("Workspace not found", 404)
    issuer = (body.issuer or "").strip().rstrip("/")
    client_id = (body.client_id or "").strip()
    if not issuer or not client_id:
        return error("The issuer and the client ID are both required", 400)
    if body.default_role not in ROLES:
        return error("The default role must be user, creator or admin", 400)
    domains, bad = clean_domains(body.domains)
    if bad:
        return error(bad, 400)
    if body.enabled and not domains:
        return error(
            "Add at least one email domain, so the sign-in page knows to send those people here",
            400,
        )
    for other in await _tenants_with_sso(db):
        if other.id == tenant.id or not _cfg(other).get("enabled"):
            continue
        taken = set(domains) & set(_cfg(other).get("domains") or [])
        if taken:
            return error(
                f"{', '.join(sorted(taken))} already signs in to another workspace", 409
            )
    old = _cfg(tenant)
    secret = (body.client_secret or "").strip()
    if not secret and not old.get("client_secret"):
        return error("The client secret is required the first time", 400)
    try:
        await discover(issuer, fresh=True)
    except SsoError as e:
        return error(str(e), 400)
    cfg = {
        "enabled": bool(body.enabled),
        "issuer": issuer,
        "client_id": client_id,
        "client_secret": (
            crypto.encrypt(tenant.id, secret) if secret else old.get("client_secret")
        ),
        "domains": domains,
        "default_role": body.default_role,
        "label": (body.label or "").strip()[:60],
        "auto_create": bool(body.auto_create),
    }
    settings = dict(tenant.settings or {})
    settings["sso"] = cfg
    tenant.settings = settings
    flag_modified(tenant, "settings")
    await log_action(
        db,
        tenant.id,
        user.id,
        "sso.configured",
        {"issuer": issuer, "domains": domains, "enabled": cfg["enabled"]},
        request,
    )
    await db.commit()
    return success(_public_cfg(tenant))


@router.delete("/api/settings/sso")
async def delete_sso(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if not _admin(user):
        return error("Only workspace admins can change single sign-on", 403)
    tenant = await db.get(Tenant, user.tenant_id)
    if tenant is None:
        return error("Workspace not found", 404)
    settings = dict(tenant.settings or {})
    settings.pop("sso", None)
    tenant.settings = settings
    flag_modified(tenant, "settings")
    await log_action(db, tenant.id, user.id, "sso.removed", None, request)
    await db.commit()
    return success(_public_cfg(tenant))


@router.post("/api/settings/sso/test")
async def test_sso(
    body: SsoConfigRequest, user: User = Depends(get_current_user)
) -> JSONResponse:
    if not _admin(user):
        return error("Only workspace admins can change single sign-on", 403)
    try:
        doc = await discover((body.issuer or "").strip(), fresh=True)
    except SsoError as e:
        return error(str(e), 400)
    return success({"ok": True, **doc})


@router.post("/api/auth/sso/discover")
async def discover_for_email(
    body: DiscoverRequest, db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    email = (body.email or "").strip().lower()
    domain = email.rsplit("@", 1)[-1] if "@" in email else email
    if not domain or not _DOMAIN.match(domain):
        return error("Enter your work email, like you@company.com", 400)
    for t in await _tenants_with_sso(db):
        c = _cfg(t)
        if c.get("enabled") and domain in (c.get("domains") or []):
            q = urllib.parse.urlencode({"login_hint": email})
            return success(
                {
                    "workspace": t.name,
                    "label": c.get("label") or t.name,
                    "start_url": f"{_api_base()}/api/auth/sso/{t.slug}/start?{q}",
                }
            )
    return error(
        f"No workspace signs in with single sign-on for {domain}. Use your password instead.",
        404,
    )


def _state_secret() -> str:
    return os.environ.get("JWT_SECRET_KEY") or os.environ.get(
        "SECRET_KEY", "dev-secret-do-not-use-in-prod"
    )


def _sign_state(slug: str, return_to: str, nonce: str) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "type": "sso_state",
            "slug": slug,
            "return_to": return_to,
            "nonce": nonce,
            "iat": now,
            "exp": now + STATE_MINUTES * 60,
        },
        _state_secret(),
        algorithm="HS256",
    )


def _read_state(state: str, slug: str) -> dict[str, Any] | None:
    try:
        p = jwt.decode(state, _state_secret(), algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    if p.get("type") != "sso_state" or p.get("slug") != slug:
        return None
    return p


def _back_to_signin(message: str) -> RedirectResponse:
    q = urllib.parse.urlencode({"sso_error": message[:300]})
    return RedirectResponse(url=f"{_web_base()}/?{q}", status_code=302)


async def _tenant_by_slug(db: AsyncSession, slug: str) -> Tenant | None:
    return (
        await db.execute(select(Tenant).where(Tenant.slug == slug))
    ).scalar_one_or_none()


@router.get("/api/auth/sso/{slug}/start")
async def start(slug: str, request: Request, db: AsyncSession = Depends(get_db)):
    tenant = await _tenant_by_slug(db, slug)
    c = _cfg(tenant)
    if tenant is None or not c.get("enabled"):
        return _back_to_signin("Single sign-on is not turned on for that workspace.")
    try:
        doc = await discover(c["issuer"])
    except SsoError as e:
        return _back_to_signin(f"Single sign-on is not reachable: {e}")
    raw_return = request.query_params.get("return_to") or "/dashboard"
    return_to = (
        raw_return
        if raw_return.startswith("/") and not raw_return.startswith("//")
        else "/dashboard"
    )
    nonce = secrets.token_urlsafe(16)
    params = {
        "client_id": c["client_id"],
        "redirect_uri": redirect_uri(slug),
        "response_type": "code",
        "scope": "openid email profile",
        "state": _sign_state(slug, return_to, nonce),
        "nonce": nonce,
    }
    hint = request.query_params.get("login_hint")
    if hint:
        params["login_hint"] = hint[:255]
    sep = "&" if "?" in doc["authorization_endpoint"] else "?"
    return RedirectResponse(
        url=doc["authorization_endpoint"] + sep + urllib.parse.urlencode(params),
        status_code=302,
    )


def _claims_of(id_token: str) -> dict[str, Any]:
    # The token came straight from the token endpoint over our own request,
    # so per OIDC core 3.1.3.7 the transport stands in for the signature.
    try:
        part = id_token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    except Exception as e:  # noqa: BLE001
        raise SsoError("The provider sent an unreadable ID token") from e


async def exchange(
    cfg: dict[str, Any], tenant: Tenant, code: str, nonce: str, slug: str
) -> dict[str, Any]:
    doc = await discover(cfg["issuer"])
    secret = crypto.decrypt(tenant.id, cfg.get("client_secret") or "")
    async with httpx.AsyncClient(timeout=15, follow_redirects=False) as c:
        r = await c.post(
            doc["token_endpoint"],
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri(slug),
                "client_id": cfg["client_id"],
                "client_secret": secret,
            },
            headers={"Accept": "application/json"},
        )
        if r.status_code != 200:
            raise SsoError(f"The provider refused the sign-in code ({r.status_code})")
        tok = r.json()
        claims = _claims_of(tok.get("id_token") or "") if tok.get("id_token") else {}
        if claims:
            aud = claims.get("aud")
            auds = aud if isinstance(aud, list) else [aud]
            if cfg["client_id"] not in auds:
                raise SsoError("The ID token was issued for another application")
            if to_public(str(claims.get("iss") or "")).rstrip("/") != cfg["issuer"]:
                raise SsoError("The ID token came from a different issuer")
            if claims.get("exp") and int(claims["exp"]) < time.time() - 60:
                raise SsoError("The ID token has expired")
            if claims.get("nonce") and claims["nonce"] != nonce:
                raise SsoError("The sign-in could not be matched to this browser")
        info: dict[str, Any] = {}
        if doc.get("userinfo_endpoint") and tok.get("access_token"):
            u = await c.get(
                doc["userinfo_endpoint"],
                headers={"Authorization": f"Bearer {tok['access_token']}"},
            )
            if u.status_code == 200:
                try:
                    info = u.json()
                except ValueError:
                    info = {}
    merged = {**claims, **{k: v for k, v in info.items() if v}}
    sub = str(merged.get("sub") or "")
    email = str(merged.get("email") or "").strip().lower()
    if not sub:
        raise SsoError("The provider did not say who signed in")
    if not email or "@" not in email:
        raise SsoError(
            "The provider did not share an email address. Allow the email scope for this app."
        )
    if merged.get("email_verified") is False:
        raise SsoError("The provider says this email address is not verified")
    name = (
        merged.get("name")
        or " ".join(
            x for x in (merged.get("given_name"), merged.get("family_name")) if x
        )
        or email.split("@")[0]
    )
    return {"sub": sub, "email": email, "name": str(name)[:255]}


async def provision(
    db: AsyncSession, tenant: Tenant, cfg: dict[str, Any], profile: dict[str, Any]
) -> tuple[User, bool]:
    """The member who signed in, and whether this sign-in created them."""
    external = f"{tenant.id}:{profile['sub']}"[:255]
    user = (
        await db.execute(
            select(User).where(
                User.auth_provider == "oidc", User.external_id == external
            )
        )
    ).scalar_one_or_none()
    if user is not None:
        if user.tenant_id != tenant.id:
            raise SsoError("This account belongs to another workspace")
        return user, False
    domain = profile["email"].rsplit("@", 1)[-1]
    if domain not in (cfg.get("domains") or []):
        raise SsoError(
            f"{profile['email']} is not in a domain this workspace signs in with single sign-on"
        )
    user = (
        await db.execute(select(User).where(func.lower(User.email) == profile["email"]))
    ).scalar_one_or_none()
    if user is not None:
        # one email is one account, a provider cannot claim someone in another workspace
        if user.tenant_id != tenant.id:
            raise SsoError(
                "An account with this email already exists in another workspace"
            )
        user.auth_provider = "oidc"
        user.external_id = external
        return user, False
    if cfg.get("auto_create") is False:
        raise SsoError(
            "You do not have an account in this workspace yet. Ask an admin to invite you."
        )
    role = cfg.get("default_role") if cfg.get("default_role") in ROLES else "user"
    user = User(
        id=uuid.uuid4(),
        email=profile["email"],
        password_hash=None,
        full_name=profile["name"],
        role=UserRole(role),
        tenant_id=tenant.id,
        auth_provider="oidc",
        external_id=external,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user, True


@router.get("/api/auth/sso/{slug}/callback")
async def callback(slug: str, request: Request, db: AsyncSession = Depends(get_db)):
    q = request.query_params
    if q.get("error"):
        return _back_to_signin(
            f"The provider stopped the sign-in: {q.get('error_description') or q.get('error')}"
        )
    state = _read_state(q.get("state") or "", slug)
    if state is None:
        return _back_to_signin(
            "The sign-in took too long or was opened twice. Try again."
        )
    tenant = await _tenant_by_slug(db, slug)
    cfg = _cfg(tenant)
    if tenant is None or not cfg.get("enabled"):
        return _back_to_signin("Single sign-on is not turned on for that workspace.")
    if not q.get("code"):
        return _back_to_signin("The provider did not send a sign-in code. Try again.")
    try:
        profile = await exchange(cfg, tenant, q["code"], state.get("nonce", ""), slug)
        user, created = await provision(db, tenant, cfg, profile)
    except SsoError as e:
        await db.rollback()
        return _back_to_signin(str(e))
    except httpx.HTTPError as e:
        await db.rollback()
        return _back_to_signin(f"The provider could not be reached: {e}")
    if not user.is_active:
        await db.rollback()
        return _back_to_signin("This account is disabled. Ask an admin.")
    await log_action(
        db,
        tenant.id,
        user.id,
        "user.registered_via_sso" if created else "user.login_sso",
        {"provider": "oidc", "issuer": cfg["issuer"], "email": user.email},
        request,
    )
    pair = await sessions.sign_in(db, user, request, "sso")
    target = (
        f"{_web_base()}/auth/callback"
        f"#access_token={urllib.parse.quote(pair['access_token'])}"
        f"&refresh_token={urllib.parse.quote(pair['refresh_token'])}"
        f"&return_to={urllib.parse.quote(state.get('return_to') or '/dashboard')}"
    )
    return RedirectResponse(url=target, status_code=302)
