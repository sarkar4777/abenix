import hashlib
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.security import verify_token

MAX_REQUEST_BODY_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_UPLOAD_BODY_BYTES = 50 * 1024 * 1024  # 50 MB

AUTH_PATHS = frozenset({
    "/api/auth/login",
    "/api/auth/register",
    "/api/auth/refresh",
})

RATE_LIMIT_SKIP = frozenset({
    "/api/health",
    "/api/health/ready",
    "/api/metrics",
    "/",
    "/docs",
    "/redoc",
    "/openapi.json",
})


class TenantMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request.state.tenant_id = None

        # Try API key first
        api_key = request.headers.get("x-api-key", "")
        if api_key.startswith("af_"):
            tenant_id = await self._resolve_tenant_from_api_key(api_key)
            if tenant_id:
                request.state.tenant_id = tenant_id
            return await call_next(request)

        # Fall back to JWT Bearer token
        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer "):
            token = auth.removeprefix("Bearer ")
            payload = verify_token(token)
            tid = payload.get("tenant_id")
            if tid:
                try:
                    request.state.tenant_id = uuid.UUID(tid)
                except ValueError:
                    pass
        return await call_next(request)

    @staticmethod
    async def _resolve_tenant_from_api_key(raw_key: str) -> uuid.UUID | None:
        """Look up tenant_id from an API key without importing deps (avoids circular imports)."""
        from app.core.deps import async_session

        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
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


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path

        if path in RATE_LIMIT_SKIP:
            return await call_next(request)

        from app.core.rate_limit import rate_limit_auth, rate_limit_user

        if path in AUTH_PATHS:
            blocked = await rate_limit_auth(request)
            if blocked:
                return blocked

        blocked = await rate_limit_user(request)
        if blocked:
            return blocked

        return await call_next(request)


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        content_length = request.headers.get("content-length")
        if content_length:
            length = int(content_length)
            is_upload = "upload" in request.url.path or "multipart" in request.headers.get("content-type", "")
            limit = MAX_UPLOAD_BODY_BYTES if is_upload else MAX_REQUEST_BODY_BYTES
            if length > limit:
                return JSONResponse(
                    status_code=413,
                    content={
                        "data": None,
                        "error": {
                            "message": "Request body too large. Max {} MB.".format(limit // (1024 * 1024)),
                            "code": 413,
                        },
                    },
                )
        return await call_next(request)
