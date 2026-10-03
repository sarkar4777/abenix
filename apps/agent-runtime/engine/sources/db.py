"""A small session pool for source tools running outside an API request."""

from __future__ import annotations

import os
from typing import Any

_factory: Any = None


def session() -> Any:
    global _factory
    if _factory is None:
        from sqlalchemy.ext.asyncio import (
            AsyncSession,
            async_sessionmaker,
            create_async_engine,
        )

        url = (
            os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_URL_ASYNC") or ""
        )
        if not url:
            raise RuntimeError(
                "DATABASE_URL is not set, watched sources cannot be read"
            )
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        engine = create_async_engine(
            url,
            pool_size=int(os.environ.get("SOURCE_DB_POOL", "3")),
            max_overflow=int(os.environ.get("SOURCE_DB_OVERFLOW", "3")),
            pool_pre_ping=True,
            pool_recycle=3600,
            connect_args={
                "server_settings": {
                    "idle_in_transaction_session_timeout": os.environ.get(
                        "DB_IDLE_TXN_TIMEOUT_MS", "300000"
                    )
                }
            },
        )
        _factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
    return _factory()
