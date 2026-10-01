"""The resolver every tool reads through, and the contract on BaseTool.

Precedence is the whole point, so each layer is pinned in turn. The refresh
must be single-flight and must keep serving when the database read fails,
because it runs inside a tool's execute and a sick settings table must not
take an agent run down.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from engine import credentials
from engine.tools.base import (
    BaseTool,
    ConfigField,
    ToolNeedsConfiguration,
    ToolResult,
)


@pytest.fixture(autouse=True)
def _clean_resolver(monkeypatch):
    # Every test starts from no stored values, a stale clock and no file.
    credentials.configure(loader=None, ttl=30)
    credentials._snapshot.clear()
    monkeypatch.setattr(credentials, "_file_defaults", {})
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("PROBE_KEY", raising=False)
    yield
    credentials.configure(loader=None, ttl=30)
    credentials._snapshot.clear()


def _loader_returning(values: dict[str, str] | None, calls: list[int]):
    async def load():
        calls.append(1)
        return values

    return load


# --- precedence --------------------------------------------------------------


def test_stored_beats_env_beats_file_beats_default(monkeypatch):
    monkeypatch.setenv("PROBE_KEY", "from-env")
    monkeypatch.setattr(credentials, "_file_defaults", {"PROBE_KEY": "from-file"})
    assert credentials.get("PROBE_KEY", default="from-default") == "from-env"
    assert credentials.source("PROBE_KEY") == "env"

    credentials._snapshot["PROBE_KEY"] = "from-store"
    assert credentials.get("PROBE_KEY") == "from-store"
    assert credentials.source("PROBE_KEY") == "stored"

    monkeypatch.delenv("PROBE_KEY")
    credentials._snapshot.clear()
    assert credentials.get("PROBE_KEY") == "from-file"
    assert credentials.source("PROBE_KEY") == "file"

    monkeypatch.setattr(credentials, "_file_defaults", {})
    assert credentials.get("PROBE_KEY", default="from-default") == "from-default"
    assert credentials.source("PROBE_KEY", default="from-default") == "default"
    assert credentials.get("PROBE_KEY") == ""
    assert credentials.source("PROBE_KEY") == "unset"


def test_override_sits_above_everything(monkeypatch):
    monkeypatch.setenv("PROBE_KEY", "from-env")
    credentials._snapshot["PROBE_KEY"] = "from-store"
    with credentials.override({"PROBE_KEY": "pinned"}):
        assert credentials.get("PROBE_KEY") == "pinned"
        assert credentials.source("PROBE_KEY") == "override"
    assert credentials.get("PROBE_KEY") == "from-store"


def test_required_raises_when_nothing_provides_it():
    with pytest.raises(ToolNeedsConfiguration) as exc:
        credentials.get("PROBE_KEY", required=True)
    assert exc.value.key == "PROBE_KEY"


def test_whitespace_only_counts_as_unset(monkeypatch):
    monkeypatch.setenv("PROBE_KEY", "   ")
    with pytest.raises(ToolNeedsConfiguration):
        credentials.get("PROBE_KEY", required=True)


# --- refresh -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_is_single_flight_and_honours_ttl():
    calls: list[int] = []
    credentials.configure(loader=_loader_returning({"PROBE_KEY": "v1"}, calls), ttl=60)
    await asyncio.gather(*(credentials.ensure_fresh() for _ in range(25)))
    assert calls == [1], "concurrent callers must share one read"
    assert credentials.get("PROBE_KEY") == "v1"
    await credentials.ensure_fresh()
    assert calls == [1], "a fresh snapshot is not re-read"
    credentials.invalidate()
    await credentials.ensure_fresh()
    assert calls == [1, 1]


@pytest.mark.asyncio
async def test_failed_read_keeps_the_previous_snapshot():
    calls: list[int] = []
    credentials.configure(loader=_loader_returning({"PROBE_KEY": "v1"}, calls), ttl=60)
    await credentials.ensure_fresh()

    async def broken():
        calls.append(1)
        raise RuntimeError("db down")

    credentials.configure(loader=broken, ttl=60)
    await credentials.ensure_fresh(force=True)
    assert credentials.get("PROBE_KEY") == "v1"
    assert credentials.snapshot_age() < 5, "a failed read still advances the clock"


@pytest.mark.asyncio
async def test_no_database_url_degrades_to_env(monkeypatch):
    monkeypatch.setenv("PROBE_KEY", "from-env")
    await credentials.ensure_fresh(force=True)
    assert credentials.get("PROBE_KEY") == "from-env"


# --- BaseTool contract ---------------------------------------------------------


class _Probe(BaseTool):
    name = "probe_tool"
    description = "probe"
    input_schema: dict[str, Any] = {"type": "object", "properties": {}}
    config_fields = (
        ConfigField(
            "PROBE_KEY",
            label="Probe key",
            kind="secret",
            required=True,
            group="Probe",
            signup_url="https://example.test/keys",
        ),
        ConfigField("PROBE_REGION", kind="string", default="eu-west-1"),
    )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        key = self.cfg("PROBE_KEY", required=True)
        return ToolResult(content=f"ran with {key} in {self.cfg('PROBE_REGION')}")


@pytest.mark.asyncio
async def test_missing_required_value_becomes_the_standard_result():
    r = await _Probe().execute({})
    assert r.is_error
    assert "PROBE_KEY is not configured" in r.content
    assert "Admin -> Tool Configuration" in r.content
    assert "https://example.test/keys" in r.content
    assert r.metadata["needs_configuration"] == "PROBE_KEY"
    assert r.metadata["tool"] == "probe_tool"


@pytest.mark.asyncio
async def test_declared_default_applies_and_wrapper_passes_through():
    with credentials.override({"PROBE_KEY": "k"}):
        r = await _Probe().execute({})
    assert not r.is_error
    assert r.content == "ran with k in eu-west-1"


def test_declaration_is_on_the_class_and_in_to_dict():
    assert _Probe.config_field("PROBE_KEY").required is True
    assert _Probe.config_field("NOPE") is None
    d = _Probe().to_dict()
    assert [f["key"] for f in d["config_fields"]] == ["PROBE_KEY", "PROBE_REGION"]
    assert _Probe.config_test({}) is None


def test_execute_is_wrapped_once_per_class():
    class _Child(_Probe):
        async def execute(self, arguments):  # type: ignore[override]
            return ToolResult(content="child")

    assert getattr(_Child.execute, "_config_wrapped", False)
    assert getattr(_Probe.execute, "_config_wrapped", False)
