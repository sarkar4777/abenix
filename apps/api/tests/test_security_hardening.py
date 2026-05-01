"""Tests for security hardening -- password hashing, JWT, scope enforcement."""
import pytest
import uuid


def test_password_hashing():
    """Passwords should be hashed with bcrypt."""
    from app.core.security import hash_password, verify_password
    hashed = hash_password("TestPassword123")
    assert hashed != "TestPassword123"
    assert verify_password("TestPassword123", hashed)
    assert not verify_password("WrongPassword", hashed)


def test_access_token_creation():
    """Access tokens should be valid JWTs."""
    from app.core.security import create_access_token, verify_token
    user_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    token = create_access_token(user_id, tenant_id, "admin")
    payload = verify_token(token)
    assert payload["sub"] == str(user_id)
    assert payload["tenant_id"] == str(tenant_id)
    assert payload["role"] == "admin"
    assert payload["type"] == "access"


def test_refresh_token_creation():
    """Refresh tokens should have correct type."""
    from app.core.security import create_refresh_token, verify_token
    user_id = uuid.uuid4()
    token = create_refresh_token(user_id)
    payload = verify_token(token)
    assert payload["sub"] == str(user_id)
    assert payload["type"] == "refresh"


def test_invalid_token_returns_empty():
    """Invalid tokens should return empty dict."""
    from app.core.security import verify_token
    result = verify_token("invalid-token-here")
    assert result == {}


def test_scope_enforcement_function():
    """require_scope should return a dependency callable."""
    from app.core.deps import require_scope
    dep = require_scope("execute")
    assert callable(dep)
