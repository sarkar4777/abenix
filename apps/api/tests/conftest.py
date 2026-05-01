import sys
from collections.abc import AsyncGenerator
from pathlib import Path
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packages" / "db"))

from models.base import Base

from app.core.config import settings
from app.core.deps import get_db
from app.main import app

engine = create_async_engine(settings.database_url, echo=False)
TestSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def _ensure_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def db_session(_ensure_tables) -> AsyncGenerator[AsyncSession, None]:
    conn = await engine.connect()
    txn = await conn.begin()
    session = AsyncSession(bind=conn, expire_on_commit=False)

    yield session

    await session.close()
    await txn.rollback()
    await conn.close()


async def _noop_rate_limit(*args, **kwargs):
    return None


@pytest.fixture(autouse=True)
def _disable_rate_limiting():
    with patch("app.core.rate_limit.rate_limit_auth", _noop_rate_limit), \
         patch("app.core.rate_limit.rate_limit_user", _noop_rate_limit):
        yield


@pytest_asyncio.fixture(loop_scope="session")
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
