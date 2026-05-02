"""Tests for the tool-level fixes shipped in the v1.0.6 wave.

Each test pins a specific bug from BUGS_TOOLS_DEEP.md so a regression
shows up on the next CI run instead of months later when an end user
files a support ticket.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

# All four helpers live under engine/tools — they intentionally don't
# depend on packages/db, so unit tests can import them in isolation.
from engine.tools._db_url import resolve_async_db_url, resolve_sync_db_url
from engine.tools._config_check import require_env, vendor_error
from engine.tools._inline_file import materialise_path
from engine.tools.atlas_tools import AtlasQueryTool
from engine.tools.base import ToolResult
from engine.tools.financial_calculator import FinancialCalculatorTool
from engine.tools.json_transformer import JsonTransformerTool

# ── _db_url helper (B-TOOL-4 + B-NEW-1) ──────────────────────────


def test_db_url_async_passthrough_when_already_async():
    out = resolve_async_db_url("postgresql+asyncpg://u:p@h:5432/db")
    assert out.startswith("postgresql+asyncpg://")


def test_db_url_async_normalises_sync_postgresql():
    out = resolve_async_db_url("postgresql://u:p@h:5432/db")
    assert out.startswith("postgresql+asyncpg://")


def test_db_url_async_normalises_postgres_scheme():
    out = resolve_async_db_url("postgres://u:p@h:5432/db")
    assert out.startswith("postgresql+asyncpg://")


def test_db_url_async_strips_ssl_param():
    """asyncpg rejects ?ssl=disable — it must be stripped, not passed
    through, otherwise the connection raises ConfigurationError."""
    out = resolve_async_db_url("postgresql+asyncpg://u:p@h:5432/db?ssl=disable")
    assert "ssl=" not in out


def test_db_url_async_strips_sslmode_param():
    out = resolve_async_db_url("postgresql+asyncpg://u:p@h:5432/db?sslmode=prefer")
    assert "sslmode=" not in out


def test_db_url_async_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:y@h/d")
    assert resolve_async_db_url("") != ""
    assert resolve_async_db_url(None) != ""


def test_db_url_async_returns_empty_when_unset(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert resolve_async_db_url("") == ""


def test_db_url_sync_converts_asyncpg_to_psycopg2():
    out = resolve_sync_db_url("postgresql+asyncpg://u:p@h:5432/db")
    assert out.startswith("postgresql+psycopg2://")


def test_db_url_sync_strips_ssl_param():
    out = resolve_sync_db_url("postgresql+asyncpg://u:p@h/d?ssl=disable")
    assert "ssl=" not in out


# ── _config_check helpers (B-TOOL-7/8/9) ──────────────────────────


def test_require_env_returns_none_when_set(monkeypatch):
    monkeypatch.setenv("FAKE_KEY", "x")
    assert require_env("FAKE_KEY", tool_name="test_tool") is None


def test_require_env_returns_error_when_missing(monkeypatch):
    monkeypatch.delenv("ANOTHER_FAKE_KEY", raising=False)
    res = require_env("ANOTHER_FAKE_KEY", tool_name="kyc_scorer", purpose="OFAC lookup")
    assert isinstance(res, ToolResult)
    assert res.is_error is True
    assert "ANOTHER_FAKE_KEY" in res.content
    assert "OFAC lookup" in res.content


def test_require_env_any_of_passes_when_one_set(monkeypatch):
    monkeypatch.delenv("KEY_A", raising=False)
    monkeypatch.setenv("KEY_B", "x")
    assert require_env("KEY_A", "KEY_B", tool_name="test") is None


def test_vendor_error_marks_is_error_with_vendor_context():
    res = vendor_error(
        "financial_calculator", "Yahoo Finance", "503 Service Unavailable"
    )
    assert res.is_error is True
    assert "Yahoo Finance" in res.content
    assert "503" in res.content


# ── _inline_file (B-NEW-2) ────────────────────────────────────────


def test_materialise_path_uses_existing_path(tmp_path):
    f = tmp_path / "real.csv"
    f.write_text("a,b\n1,2\n")
    out, err = materialise_path({"path": str(f)})
    assert err == ""
    assert out == str(f)


def test_materialise_path_writes_inline_text_to_temp(tmp_path, monkeypatch):
    monkeypatch.setenv("EXPORT_DIR", str(tmp_path))
    out, err = materialise_path({"text": "name,score\nA,10\nB,20\n", "format": "csv"})
    assert err == ""
    assert out.endswith(".csv")
    with open(out) as fh:
        assert "name,score" in fh.read()


def test_materialise_path_serialises_json_inline_payload(tmp_path, monkeypatch):
    monkeypatch.setenv("EXPORT_DIR", str(tmp_path))
    out, err = materialise_path({"text": {"k": [1, 2, 3]}, "format": "json"})
    assert err == ""
    with open(out) as fh:
        body = fh.read()
    assert '"k"' in body
    # JSON is pretty-printed multi-line; check for the values rather
    # than a specific format.
    assert "1" in body and "2" in body and "3" in body


def test_materialise_path_returns_error_when_neither_provided():
    out, err = materialise_path({})
    assert out == ""
    assert "path" in err.lower()
    assert "text" in err.lower()


def test_materialise_path_reports_missing_file():
    out, err = materialise_path({"path": "/nonexistent/file.txt"})
    assert out == ""
    assert "not found" in err.lower()


# ── atlas_query coercion (B-TOOL-2) ───────────────────────────────


@pytest.mark.asyncio
async def test_atlas_query_accepts_query_keyword():
    """Backward-compat: pipelines authored with `query: 'Asset'` must
    not be rejected. The tool used to fail with 'No patterns supplied.'"""
    tool = AtlasQueryTool(tenant_id="t", agent_id="a")
    # Mock the DB pool to avoid hitting Postgres in unit tests.
    with patch("engine.tools.atlas_tools._pool") as mock_pool:
        # Make the pool acquire a context manager that does nothing
        # interesting — we only want to verify we got past the
        # "No patterns supplied" early return.
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def fake_acquire():
            class FakeConn:
                async def fetch(self, *a, **k):
                    return []

                async def fetchrow(self, *a, **k):
                    return None

                async def fetchval(self, *a, **k):
                    return None

            yield FakeConn()

        class FakePool:
            def acquire(self):
                return fake_acquire()

        async def fake_pool():
            return FakePool()

        mock_pool.side_effect = fake_pool
        res = await tool.execute({"query": "Asset"})

    assert res.is_error is False or "No patterns supplied" not in res.content


@pytest.mark.asyncio
async def test_atlas_query_returns_helpful_error_when_truly_empty():
    tool = AtlasQueryTool(tenant_id="t", agent_id="a")
    res = await tool.execute({})
    assert res.is_error is True
    assert "patterns" in res.content.lower()
    assert "query" in res.content.lower()


@pytest.mark.asyncio
async def test_atlas_query_accepts_string_pattern_list():
    """Some seeded pipelines use `patterns: ["Asset"]` (string list)
    instead of the canonical `[{label_like: 'Asset'}]`. The tool must
    coerce, not reject."""
    tool = AtlasQueryTool(tenant_id="t", agent_id="a")
    with patch("engine.tools.atlas_tools._pool") as mock_pool:
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def fake_acquire():
            class FakeConn:
                async def fetch(self, *a, **k):
                    return []

                async def fetchrow(self, *a, **k):
                    return None

                async def fetchval(self, *a, **k):
                    return None

            yield FakeConn()

        class FakePool:
            def acquire(self):
                return fake_acquire()

        async def fake_pool():
            return FakePool()

        mock_pool.side_effect = fake_pool
        res = await tool.execute({"patterns": ["Asset", "Obligation"]})

    assert "No patterns supplied" not in res.content


# ── json_transformer identity / pass-through (B-TOOL-3) ───────────


@pytest.mark.asyncio
async def test_json_transformer_identity_returns_data_unchanged():
    tool = JsonTransformerTool()
    res = await tool.execute({"data": {"a": 1, "b": [1, 2]}, "operation": "identity"})
    assert res.is_error is False
    # Output is JSON-encoded, parse it back.
    import json as _json

    assert _json.loads(res.content) == {"a": 1, "b": [1, 2]}


@pytest.mark.asyncio
async def test_json_transformer_omitted_operation_is_identity():
    tool = JsonTransformerTool()
    res = await tool.execute({"data": [1, 2, 3]})
    assert res.is_error is False
    import json as _json

    assert _json.loads(res.content) == [1, 2, 3]


@pytest.mark.asyncio
async def test_json_transformer_noop_alias_works():
    tool = JsonTransformerTool()
    res = await tool.execute({"data": {"k": "v"}, "operation": "noop"})
    assert res.is_error is False
    assert "k" in res.content


@pytest.mark.asyncio
async def test_json_transformer_unknown_operation_lists_valid_options():
    tool = JsonTransformerTool()
    res = await tool.execute({"data": {"k": 1}, "operation": "magic"})
    assert res.is_error is True
    # Error message MUST list the supported operations so the LLM can
    # self-correct on retry.
    assert "Valid operations" in res.content
    assert "identity" in res.content
    assert "filter" in res.content


# ── financial_calculator future_value (B-TOOL-5) ──────────────────


@pytest.mark.asyncio
async def test_financial_calculator_future_value_compound_annual():
    tool = FinancialCalculatorTool()
    res = await tool.execute(
        {
            "calculation": "future_value",
            "params": {"present": 1000, "rate": 0.05, "years": 10},
        }
    )
    assert res.is_error is False
    import json as _json

    out = _json.loads(res.content)
    # FV of $1000 at 5% for 10 years compounded annually = $1628.89
    assert 1628 < out["future_value"] < 1629


@pytest.mark.asyncio
async def test_financial_calculator_present_value():
    tool = FinancialCalculatorTool()
    res = await tool.execute(
        {
            "calculation": "present_value",
            "params": {"future": 1628.89, "rate": 0.05, "years": 10},
        }
    )
    assert res.is_error is False
    import json as _json

    out = _json.loads(res.content)
    assert 999 < out["present_value"] < 1001


@pytest.mark.asyncio
async def test_financial_calculator_compound_interest_schedule():
    tool = FinancialCalculatorTool()
    res = await tool.execute(
        {
            "calculation": "compound_interest",
            "params": {"principal": 1000, "rate": 0.05, "years": 10},
        }
    )
    assert res.is_error is False
    import json as _json

    out = _json.loads(res.content)
    assert len(out["schedule"]) == 10
    assert out["final_balance"] > 1500
    assert out["total_interest"] > 500
