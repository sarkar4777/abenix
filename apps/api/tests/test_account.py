"""Tests for GDPR account endpoints — data export and deletion."""

import pytest
from unittest.mock import MagicMock
import uuid


@pytest.fixture
def mock_user():
    user = MagicMock()
    user.id = uuid.uuid4()
    user.tenant_id = uuid.uuid4()
    user.email = "test@example.com"
    user.full_name = "Test User"
    user.role = MagicMock(value="user")
    user.created_at = None
    user.notification_settings = {}
    user.is_active = True
    return user


def test_export_endpoint_exists():
    """3.1 — Data export endpoint should be registered."""
    from app.routers.account import router

    paths = [r.path for r in router.routes]
    assert "/export" in paths or any("/export" in str(p) for p in paths)


def test_delete_endpoint_exists():
    """3.2 — Account deletion endpoint should be registered."""
    from app.routers.account import router

    methods = []
    for route in router.routes:
        if hasattr(route, "methods"):
            methods.extend(route.methods)
    assert "DELETE" in methods


def test_privacy_endpoint_exists():
    """3.6 — Privacy settings endpoint should be registered."""
    from app.routers.account import router

    paths = [r.path for r in router.routes]
    assert "/privacy" in paths or any("/privacy" in str(p) for p in paths)


def test_retention_policy_parsing():
    """3.4 — Retention policy parsing with minimum enforcement."""
    from app.core.retention import parse_retention_settings

    policy = parse_retention_settings({"execution_retention_days": 3})
    assert policy.execution_retention_days == 7  # minimum enforced


def test_retention_policy_defaults():
    """3.4 — Retention policy defaults."""
    from app.core.retention import parse_retention_settings

    policy = parse_retention_settings({})
    assert policy.execution_retention_days == 90
    assert policy.message_retention_days == 365
    assert policy.audit_log_retention_days == 730
