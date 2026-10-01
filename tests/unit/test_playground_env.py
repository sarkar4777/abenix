"""The playground subprocess must never inherit the API pod's environment."""

from __future__ import annotations

import os
from unittest.mock import patch

from app.routers.sdk_playground import (
    _USER_ENV_ALLOWLIST,
    build_sandbox_env,
    playground_api_url,
)

POD_ENV = {
    "PATH": "/usr/bin:/bin",
    "DATABASE_URL": "postgresql://u:p@db/abenix",
    "REDIS_URL": "redis://redis:6379/0",
    "SECRET_KEY": "super-secret",
    "JWT_PRIVATE_KEY": "-----BEGIN",
    "ANTHROPIC_API_KEY": "sk-ant-xxx",
    "OPENAI_API_KEY": "sk-xxx",
    "ABENIX_DATA_KEY_KEK_BASE64": "kek",
    "SMTP_PASS": "mailpass",
    "HOME": "/root",
    "KUBERNETES_SERVICE_HOST": "10.0.0.1",
}


def _env(user_env=None):
    with patch.dict(os.environ, POD_ENV, clear=True):
        return build_sandbox_env(
            api_key="af_pg_test",
            base_url="http://localhost:8000",
            home="/tmp/pg-home",
            user_env=user_env,
        )


def test_inherited_secrets_never_reach_the_sandbox():
    env = _env()
    for name in (
        "DATABASE_URL",
        "REDIS_URL",
        "SECRET_KEY",
        "JWT_PRIVATE_KEY",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "ABENIX_DATA_KEY_KEK_BASE64",
        "SMTP_PASS",
        "KUBERNETES_SERVICE_HOST",
    ):
        assert name not in env


def test_sandbox_has_only_what_the_sdk_needs():
    env = _env()
    assert env["PATH"] == "/usr/bin:/bin"
    assert env["HOME"] == "/tmp/pg-home"
    assert env["ABENIX_API_KEY"] == "af_pg_test"
    assert env["ABENIX_BASE_URL"] == "http://localhost:8000"
    assert env["ABENIX_API_URL"] == "http://localhost:8000"
    assert env["PYTHONPATH"].endswith(os.path.join("sdk", "python"))
    assert env["PYTHONIOENCODING"] == "utf-8"
    assert env["LANG"]
    allowed_prefixes = (
        "PATH",
        "HOME",
        "LANG",
        "LC_ALL",
        "PYTHON",
        "ABENIX_",
        "USERPROFILE",
        "SYSTEMROOT",
        "COMSPEC",
        "PATHEXT",
        "TEMP",
        "TMP",
        "WINDIR",
    )
    for name in env:
        assert name.startswith(allowed_prefixes), name


def test_user_env_is_filtered_by_sensitive_name_patterns():
    env = _env(
        {
            "MY_FLAG": "1",
            "DATABASE_URL": "postgresql://evil",
            "SOME_TOKEN": "t",
            "APP_PASSWORD": "p",
            "AWS_SECRET_ACCESS_KEY": "k",
            "CALLBACK_URL": "http://x",
            "PATH": "/evil",
            "ABENIX_API_KEY": "af_other",
            "bad name": "x",
            "ABENIX_API_URL": "http://custom:9000",
        }
    )
    assert env["MY_FLAG"] == "1"
    assert "DATABASE_URL" not in env
    assert "SOME_TOKEN" not in env
    assert "APP_PASSWORD" not in env
    assert "AWS_SECRET_ACCESS_KEY" not in env
    assert "CALLBACK_URL" not in env
    assert "bad name" not in env
    # protected keys win over user input even when allowlisted
    assert env["PATH"] == "/usr/bin:/bin"
    assert env["ABENIX_API_KEY"] == "af_pg_test"
    assert env["ABENIX_API_URL"] == "http://localhost:8000"
    assert "ABENIX_API_URL" in _USER_ENV_ALLOWLIST


def test_playground_api_url_defaults_to_local_api():
    with patch.dict(os.environ, {}, clear=True):
        assert playground_api_url() == "http://localhost:8000"
    with patch.dict(os.environ, {"PLAYGROUND_INTERNAL_API_URL": "http://api:8000"}):
        assert playground_api_url() == "http://api:8000"
