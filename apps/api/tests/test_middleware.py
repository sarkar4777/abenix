"""Tests for middleware -- rate limiting, body size, tenant resolution."""
import pytest


def test_rate_limit_constants():
    """Rate limit skip paths should include health endpoints."""
    from app.core.middleware import RATE_LIMIT_SKIP
    assert "/api/health" in RATE_LIMIT_SKIP
    assert "/api/metrics" in RATE_LIMIT_SKIP


def test_body_size_limits():
    """Body size limits should be configured correctly."""
    from app.core.middleware import MAX_REQUEST_BODY_BYTES, MAX_UPLOAD_BODY_BYTES
    assert MAX_REQUEST_BODY_BYTES == 10 * 1024 * 1024  # 10 MB
    assert MAX_UPLOAD_BODY_BYTES == 50 * 1024 * 1024  # 50 MB


def test_auth_paths():
    """Auth paths should include login, register, refresh."""
    from app.core.middleware import AUTH_PATHS
    assert "/api/auth/login" in AUTH_PATHS
    assert "/api/auth/register" in AUTH_PATHS
    assert "/api/auth/refresh" in AUTH_PATHS


def test_tenant_middleware_class():
    """TenantMiddleware should be importable."""
    from app.core.middleware import TenantMiddleware
    assert TenantMiddleware is not None


def test_rate_limit_middleware_class():
    """RateLimitMiddleware should be importable."""
    from app.core.middleware import RateLimitMiddleware
    assert RateLimitMiddleware is not None
