"""The warm path caches asset rows briefly so a burst does not queue on the db pool."""

from __future__ import annotations

import asyncio

import pytest

from engine.tools import code_asset as ca


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    ca._HOT.clear()
    ca._HOT_LOCKS.clear()
    monkeypatch.setenv("CODE_ASSET_CACHE_SECONDS", "2")
    yield
    ca._HOT.clear()
    ca._HOT_LOCKS.clear()


def test_burst_loads_once() -> None:
    calls = 0

    async def load():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return {"id": "a"}

    async def main():
        return await asyncio.gather(
            *[ca._hot(("asset", "t", "a"), load) for _ in range(200)]
        )

    out = asyncio.run(main())
    assert calls == 1
    assert all(o == {"id": "a"} for o in out)


def test_missing_rows_are_not_cached() -> None:
    calls = 0

    async def load():
        nonlocal calls
        calls += 1
        return None

    async def main():
        await ca._hot(("asset", "t", "x"), load)
        await ca._hot(("asset", "t", "x"), load)

    asyncio.run(main())
    assert calls == 2


def test_zero_ttl_turns_it_off(monkeypatch) -> None:
    monkeypatch.setenv("CODE_ASSET_CACHE_SECONDS", "0")
    calls = 0

    async def load():
        nonlocal calls
        calls += 1
        return {}

    async def main():
        for _ in range(3):
            await ca._hot(("secrets", "t", "a"), load)

    asyncio.run(main())
    assert calls == 3
