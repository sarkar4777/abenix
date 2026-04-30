"""Async SQLAlchemy engine + session setup for ResolveAI."""
from __future__ import annotations

import logging
import os
from typing import AsyncIterator

logger = logging.getLogger("resolveai.db")

_engine = None
_sessionmaker = None
db_enabled: bool = False


def _normalise_url(raw: str) -> str:
    """Coerce a sync PG URL to the asyncpg driver."""
    if raw.startswith("postgresql+asyncpg://"):
        return raw
    if raw.startswith("postgresql://"):
        return "postgresql+asyncpg://" + raw[len("postgresql://"):]
    if raw.startswith("postgres://"):
        return "postgresql+asyncpg://" + raw[len("postgres://"):]
    return raw


try:
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )

    _raw_url = os.environ.get("DATABASE_URL", "").strip()
    if _raw_url:
        try:
            _engine = create_async_engine(
                _normalise_url(_raw_url),
                pool_pre_ping=True,
                pool_size=int(os.environ.get("RESOLVEAI_DB_POOL_SIZE", "10")),
                max_overflow=int(os.environ.get("RESOLVEAI_DB_MAX_OVERFLOW", "20")),
                future=True,
            )
            _sessionmaker = async_sessionmaker(
                bind=_engine, expire_on_commit=False, class_=AsyncSession,
            )
            db_enabled = True
            logger.info("ResolveAI DB enabled (async engine up)")
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "DATABASE_URL set but engine failed to build (%s) — falling back to in-memory",
                exc,
            )
            _engine = None
            _sessionmaker = None
            db_enabled = False
    else:
        logger.info("DATABASE_URL not set — running with in-memory case store")
except Exception as exc:  # noqa: BLE001
    # SQLAlchemy or asyncpg isn't installed; keep the walking skeleton alive.
    logger.warning("SQLAlchemy async not available (%s) — forcing in-memory store", exc)
    db_enabled = False


def get_engine():
    """Return the module-level async engine (may be None)."""
    return _engine


def get_sessionmaker():
    """Return the async_sessionmaker (may be None if db disabled)."""
    return _sessionmaker


async def get_db() -> AsyncIterator:
    """FastAPI dependency: yields an ``AsyncSession`` or raises 503."""
    if not db_enabled or _sessionmaker is None:
        yield None
        return

    async with _sessionmaker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_tables() -> None:
    """Create every ResolveAI table if it doesn't already exist."""
    if not db_enabled or _engine is None:
        logger.info("init_tables() skipped — db not enabled")
        return

    # Import here so model registration happens before create_all runs.
    from app.models import Base  # noqa: WPS433 (local import on purpose)

    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    logger.info("ResolveAI tables ensured (%d tables)", len(Base.metadata.tables))
