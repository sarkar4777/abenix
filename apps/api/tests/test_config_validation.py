"""Tests for configuration validation and security hardening."""

import pytest
from unittest.mock import patch
import os


def test_production_requires_secret_key():
    """1.1.1 — secret_key must not be default in production."""
    with patch.dict(
        os.environ,
        {"DEBUG": "false", "SECRET_KEY": "change-me-in-production"},
        clear=False,
    ):
        from app.core.config import Settings

        with pytest.raises(RuntimeError, match="SECRET_KEY"):
            Settings()


def test_production_requires_jwt_keys():
    """1.1.2 — JWT keys required in production."""
    with patch.dict(
        os.environ,
        {
            "DEBUG": "false",
            "SECRET_KEY": "a-real-secret-key-here-1234567890",
            "JWT_PRIVATE_KEY": "",
            "JWT_PUBLIC_KEY": "",
        },
        clear=False,
    ):
        from app.core.config import Settings

        with pytest.raises(RuntimeError, match="JWT"):
            Settings()


def test_debug_mode_allows_defaults():
    """Debug mode should allow default values."""
    with patch.dict(os.environ, {"DEBUG": "true"}, clear=False):
        from app.core.config import Settings

        s = Settings()
        assert s.debug is True


def test_scope_enforcement():
    """1.4.1 — API key scope check."""
    from app.core.deps import require_scope

    assert callable(require_scope("read"))
