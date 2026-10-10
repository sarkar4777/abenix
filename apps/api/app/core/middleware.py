import hashlib
import time
import uuid

from starlette.datastructures import Headers, MutableHeaders
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.security import verify_token

MAX_REQUEST_BODY_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_UPLOAD_BODY_BYTES = 50 * 1024 * 1024  # 50 MB

API_KEY_CACHE_TTL_SECONDS = 30.0
API_KEY_CACHE_MAX_ENTRIES = 4096

AUTH_PATHS = frozenset(
    {
        "/api/auth/login",
        "/api/auth/register",
        "/api/auth/refresh",
        "/api/auth/accept-invite",
        "/api/auth/login/2fa",
        "/api/auth/forgot-password",
        "/api/auth/reset-password",
        "/api/auth/sso/discover",
    }
)

RATE_LIMIT_SKIP = frozenset(
    {
        "/api/health",
        "/api/health/ready",
        "/api/metrics",
        "/",
        "/docs",
        "/redoc",
        "/openapi.json",
    }
)

_SECURITY_HEADERS = (
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "strict-origin-when-cross-origin"),
    ("X-Frame-Options", "DENY"),
    ("Strict-Transport-Security", "max-age=31536000; includeSubDomains"),
)

_CSP = (
    "default-src 'self'; frame-ancestors 'none'; "
    "img-src 'self' data: blob: https:; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "connect-src 'self' https: wss:"
)


class TenantMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self._cache: dict[str, tuple[float, uuid.UUID]] = {}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        state = scope.setdefault("state", {})
        state["tenant_id"] = None
        headers = Headers(scope=scope)

        api_key = headers.get("x-api-key", "")
        if api_key.startswith("af_"):
            tenant_id = await self._tenant_for_api_key(api_key)
            if tenant_id:
                state["tenant_id"] = tenant_id
            await self.app(scope, receive, send)
            return

        auth = headers.get("authorization", "")
        if auth.startswith("Bearer "):
            payload = verify_token(auth.removeprefix("Bearer "))
            tid = payload.get("tenant_id")
            if tid:
                try:
                    state["tenant_id"] = uuid.UUID(tid)
                except ValueError:
                    pass
        await self.app(scope, receive, send)

    async def _tenant_for_api_key(self, raw_key: str) -> uuid.UUID | None:
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        now = time.monotonic()
        hit = self._cache.get(key_hash)
        if hit is not None:
            if hit[0] > now:
                return hit[1]
            self._cache.pop(key_hash, None)

        tenant_id = await self._resolve_tenant_from_api_key(key_hash)
        # Misses are not cached so a freshly created key works at once.
        if tenant_id is not None:
            if len(self._cache) >= API_KEY_CACHE_MAX_ENTRIES:
                self._evict(now)
            self._cache[key_hash] = (now + API_KEY_CACHE_TTL_SECONDS, tenant_id)
        return tenant_id

    def _evict(self, now: float) -> None:
        for k in [k for k, (exp, _) in self._cache.items() if exp <= now]:
            del self._cache[k]
        while len(self._cache) >= API_KEY_CACHE_MAX_ENTRIES:
            del self._cache[next(iter(self._cache))]

    @staticmethod
    async def _resolve_tenant_from_api_key(key_hash: str) -> uuid.UUID | None:
        """Look up tenant_id from an API key without importing deps (avoids circular imports)."""
        from app.core.deps import async_session

        async with async_session() as db:
            from sqlalchemy import select

            from models.api_key import ApiKey

            result = await db.execute(
                select(ApiKey.tenant_id).where(
                    ApiKey.key_hash == key_hash, ApiKey.is_active.is_(True)
                )
            )
            row = result.first()
            return row[0] if row else None


class RateLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in RATE_LIMIT_SKIP:
            await self.app(scope, receive, send)
            return

        from app.core.rate_limit import rate_limit_auth, rate_limit_user

        path = scope["path"]
        request = Request(scope)

        if path in AUTH_PATHS or path.startswith("/api/auth/invite/"):
            blocked = await rate_limit_auth(request)
            if blocked:
                await blocked(scope, receive, send)
                return

        blocked = await rate_limit_user(request)
        if blocked:
            await blocked(scope, receive, send)
            return

        await self.app(scope, receive, send)


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope["path"]
        add_csp = not (
            path.startswith("/docs")
            or path.startswith("/redoc")
            or path == "/openapi.json"
        )

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in _SECURITY_HEADERS:
                    headers.setdefault(name, value)
                if add_csp:
                    headers.setdefault("Content-Security-Policy", _CSP)
            await send(message)

        await self.app(scope, receive, send_wrapper)


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        content_length = headers.get("content-length")
        if content_length:
            length = int(content_length)
            is_upload = "upload" in scope["path"] or "multipart" in headers.get(
                "content-type", ""
            )
            limit = MAX_UPLOAD_BODY_BYTES if is_upload else MAX_REQUEST_BODY_BYTES
            if length > limit:
                response = JSONResponse(
                    status_code=413,
                    content={
                        "data": None,
                        "error": {
                            "message": "Request body too large. Max {} MB.".format(
                                limit // (1024 * 1024)
                            ),
                            "code": 413,
                        },
                    },
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
