"""One pooled engine per database and event loop for runtime code that reads the db per call."""

from __future__ import annotations

import asyncio
import os
from typing import Any

_ENGINES: dict[tuple[int, str], Any] = {}


def shared_engine(db_url: str) -> Any:
    from sqlalchemy.ext.asyncio import create_async_engine

    key = (id(asyncio.get_running_loop()), db_url)
    eng = _ENGINES.get(key)
    if eng is None:
        eng = create_async_engine(
            db_url,
            pool_size=int(os.environ.get("RUNTIME_DB_POOL_SIZE", "5")),
            max_overflow=int(os.environ.get("RUNTIME_DB_MAX_OVERFLOW", "5")),
            pool_timeout=30,
            pool_recycle=300,
            pool_pre_ping=True,
        )
        _ENGINES[key] = eng
    return eng
