from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def sync_missing_columns(engine: Any, base: Any) -> int:
    from sqlalchemy import inspect, text

    added = 0
    async with engine.begin() as conn:
        for tbl in base.metadata.sorted_tables:
            try:
                existing_cols = await conn.run_sync(
                    lambda sync_conn, name=tbl.name: {
                        c["name"] for c in inspect(sync_conn).get_columns(name)
                    }
                )
            except Exception:
                continue
            for col in tbl.columns:
                if col.name in existing_cols:
                    continue
                try:
                    col_type = col.type.compile(dialect=conn.dialect)
                    stmt = (
                        f'ALTER TABLE "{tbl.name}" ADD COLUMN IF NOT EXISTS '
                        f'"{col.name}" {col_type}'
                    )
                    await conn.execute(text(stmt))
                    added += 1
                    logger.info("schema_sync: added %s.%s", tbl.name, col.name)
                except Exception as e:
                    logger.warning(
                        "schema_sync: failed %s.%s: %s", tbl.name, col.name, e
                    )
    return added
