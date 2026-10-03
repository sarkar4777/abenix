"""Auth under load: one db read per user when the cache is cold, and a busy db is a 503 not a 401."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import TimeoutError as PoolTimeout

from app.core import principal as P


@pytest.fixture(autouse=True)
def _fresh():
    P._cache.clear()
    P._loading.clear()
    yield
    P._cache.clear()
    P._loading.clear()


def _jwt_for(uid: uuid.UUID, monkeypatch) -> str:
    monkeypatch.setattr(
        P, "verify_token", lambda t: {"sub": str(uid), "type": "access"}
    )
    return "tok"


def test_cold_cache_loads_a_user_once(monkeypatch) -> None:
    uid = uuid.uuid4()
    loads = 0

    async def load(k, u):
        nonlocal loads
        loads += 1
        await asyncio.sleep(0.02)
        p = P.Principal(
            id=u, tenant_id=uuid.uuid4(), role="admin", email="a@b.c", via="jwt"
        )
        P._put(k, p)
        return p

    monkeypatch.setattr(P, "_load_user", load)
    tok = _jwt_for(uid, monkeypatch)

    async def main():
        return await asyncio.gather(
            *[
                P.current_principal(authorization=f"Bearer {tok}", x_api_key=None)
                for _ in range(200)
            ]
        )

    out = asyncio.run(main())
    assert loads == 1
    assert {p.id for p in out} == {uid}


def test_a_saturated_pool_is_a_503(monkeypatch) -> None:
    async def load(k, u):
        raise PoolTimeout("QueuePool limit reached")

    monkeypatch.setattr(P, "_load_user", load)
    tok = _jwt_for(uuid.uuid4(), monkeypatch)
    with pytest.raises(HTTPException) as e:
        asyncio.run(P.current_principal(authorization=f"Bearer {tok}", x_api_key=None))
    assert e.value.status_code == 503
    assert e.value.headers["Retry-After"]


def test_a_bad_token_is_still_a_401(monkeypatch) -> None:
    def bad(t):
        raise ValueError("signature")

    monkeypatch.setattr(P, "verify_token", bad)
    with pytest.raises(HTTPException) as e:
        asyncio.run(P.current_principal(authorization="Bearer nope", x_api_key=None))
    assert e.value.status_code == 401
