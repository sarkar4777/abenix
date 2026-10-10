"""A direct tool call answers before its log row is written, and the row keeps a preview of large payloads."""

from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace

from app.routers import tools


def test_small_values_are_kept_whole():
    assert tools._clip({"a": 1}) == {"a": 1}
    assert tools._clip("short") == "short"
    assert tools._clip(None) is None


def test_large_values_keep_a_preview_and_their_size():
    big = {"state": "x" * 20_000}
    out = tools._clip(big)
    assert out["truncated"] is True
    assert out["size"] > 20_000
    assert len(out["preview"]) == tools._LOG_KEEP_CHARS
    text = tools._clip("y" * 20_000)
    assert json.loads(text)["truncated"] is True


def test_the_log_row_is_written_in_the_background(monkeypatch):
    from app.core import deps

    added = []

    class Session:
        def add(self, row):
            added.append(row)

        async def commit(self):
            await asyncio.sleep(0.05)

    @asynccontextmanager
    async def factory():
        yield Session()

    monkeypatch.setattr(deps, "async_session", factory)
    user = SimpleNamespace(tenant_id=uuid.uuid4(), id=uuid.uuid4())

    async def scenario():
        result = SimpleNamespace(content="ok", metadata={}, is_error=False)
        await tools._log_invocation(
            None, user, "code_asset", {"arguments": {}}, result, 0.0, status="ok"
        )
        # the caller is not held up by the commit
        assert added == []
        await asyncio.gather(*list(tools._LOG_TASKS))
        assert len(added) == 1

    asyncio.run(scenario())
