"""Admin limits reach the runtime pod even without the API's settings module."""

from __future__ import annotations

import builtins

import pytest

from engine import runtime_settings


@pytest.fixture
def no_api_settings(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "app.core.platform_settings":
            raise ImportError("not in the runtime image")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setattr(runtime_settings, "_cache", {})


@pytest.mark.asyncio
async def test_reads_the_table_when_the_api_module_is_missing(
    no_api_settings, monkeypatch
):
    async def row(key):
        return {"pipeline.timeout_seconds": "1800"}.get(key)

    monkeypatch.setattr(runtime_settings, "_read_row", row)
    assert (
        await runtime_settings.get_int_setting("pipeline.timeout_seconds", 300) == 1800
    )
    assert await runtime_settings.get_int_setting("sandbox.timeout_seconds", 300) == 300


@pytest.mark.asyncio
async def test_unreadable_table_keeps_the_default(no_api_settings, monkeypatch):
    async def broken(key):
        raise RuntimeError("db down")

    monkeypatch.setattr(runtime_settings, "_read_row", broken)
    assert (
        await runtime_settings.get_int_setting("pipeline.timeout_seconds", 300) == 300
    )


@pytest.mark.asyncio
async def test_pipeline_budget_uses_the_admin_setting(no_api_settings, monkeypatch):
    import consumer

    async def row(key):
        return "1200"

    monkeypatch.setattr(runtime_settings, "_read_row", row)
    assert await consumer._pipeline_timeout() == 1200
