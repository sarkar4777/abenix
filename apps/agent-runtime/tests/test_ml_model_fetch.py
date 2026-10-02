"""The runtime fetches a model file it cannot see, once, and caches it."""

from __future__ import annotations

import httpx
import pytest

from engine.tools import invoke_agent, ml_model_tool


@pytest.mark.asyncio
async def test_existing_file_is_used_as_is(tmp_path):
    f = tmp_path / "m.pkl"
    f.write_bytes(b"x")
    assert await ml_model_tool._ensure_local("id1", str(f), "t1") == str(f)


@pytest.mark.asyncio
async def test_missing_file_is_fetched_once_and_cached(tmp_path, monkeypatch):
    monkeypatch.setattr(ml_model_tool.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(invoke_agent, "mint_fetch_token", lambda *a, **k: "tok")
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.headers["authorization"] == "Bearer tok"
        assert request.url.path.endswith("/api/ml-models/id2/fetch")
        return httpx.Response(200, content=b"model-bytes")

    real = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: real(transport=httpx.MockTransport(handler), **kw),
    )
    first = await ml_model_tool._ensure_local("id2", "/gone/abc_m.pkl", "t1")
    second = await ml_model_tool._ensure_local("id2", "/gone/abc_m.pkl", "t1")
    assert first == second
    assert open(first, "rb").read() == b"model-bytes"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_refused_fetch_says_why(tmp_path, monkeypatch):
    monkeypatch.setattr(ml_model_tool.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(invoke_agent, "mint_fetch_token", lambda *a, **k: "tok")
    real = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: real(
            transport=httpx.MockTransport(lambda r: httpx.Response(404)), **kw
        ),
    )
    with pytest.raises(FileNotFoundError, match="404"):
        await ml_model_tool._ensure_local("id3", "/gone/x.pkl", "t1")
