"""A dropped model stream is read again from the start, once."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from engine.agent_executor import collect_stream

pytestmark = pytest.mark.asyncio


def _token(text):
    return SimpleNamespace(event="token", data=text)


class Router:
    def __init__(self, drops):
        self.drops = drops
        self.calls = 0

    async def complete(self, **kwargs):
        self.calls += 1
        call = self.calls

        async def stream():
            yield _token("partial " if call <= self.drops else "whole")
            if call <= self.drops:
                raise httpx.RemoteProtocolError("peer closed connection")
            yield SimpleNamespace(event="done", data={"stop_reason": "end_turn"})

        return stream()


async def test_a_dropped_stream_is_read_again_without_the_partial_text():
    router = Router(drops=1)
    text, tools, meta = await collect_stream(router, {})
    assert router.calls == 2
    assert text == "whole"
    assert tools == []
    assert meta["stop_reason"] == "end_turn"


async def test_it_gives_up_after_the_second_drop():
    router = Router(drops=2)
    with pytest.raises(httpx.RemoteProtocolError):
        await collect_stream(router, {})
    assert router.calls == 2
