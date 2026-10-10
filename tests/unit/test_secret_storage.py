"""Startup check and status for secrets stored without a KEK."""

from __future__ import annotations

import base64
import logging

import pytest

from app.core import secret_storage as ss

KEK = base64.b64encode(b"k" * 32).decode()


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for k in (
        "ABENIX_DATA_KEY_KEK_BASE64",
        "ENVIRONMENT",
        "ABENIX_ALLOW_PLAINTEXT_SECRETS",
    ):
        monkeypatch.delenv(k, raising=False)


def test_dev_without_a_key_warns_and_starts(caplog, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "local")
    with caplog.at_level(logging.WARNING):
        ss.check_at_startup()
    assert "Secrets are stored unencrypted" in caplog.text
    st = ss.status()
    assert (
        st["encrypted_at_rest"] is False
        and "ABENIX_DATA_KEY_KEK_BASE64" in st["message"]
    )


def test_production_without_a_key_refuses_to_start(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    with pytest.raises(RuntimeError, match="ABENIX_ALLOW_PLAINTEXT_SECRETS"):
        ss.check_at_startup()


def test_production_opt_out_starts_with_a_warning(caplog, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("ABENIX_ALLOW_PLAINTEXT_SECRETS", "true")
    with caplog.at_level(logging.WARNING):
        ss.check_at_startup()
    assert "unencrypted" in caplog.text


def test_staging_is_not_production(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "staging")
    ss.check_at_startup()


def test_a_bad_key_counts_as_none(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv(
        "ABENIX_DATA_KEY_KEK_BASE64", base64.b64encode(b"short").decode()
    )
    with pytest.raises(RuntimeError):
        ss.check_at_startup()


def test_production_with_a_key_is_quiet(caplog, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("ABENIX_DATA_KEY_KEK_BASE64", KEK)
    with caplog.at_level(logging.WARNING):
        ss.check_at_startup()
    assert "unencrypted" not in caplog.text
    assert ss.status() == {
        "encrypted_at_rest": True,
        "message": None,
        "doc_slug": ss.DOC_SLUG,
        "environment": "production",
    }
