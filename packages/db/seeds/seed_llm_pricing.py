"""Seed the model pricing catalogue. Run by deploy after the schema is up.

The rows come from pricing_baseline.py, the same source the admin endpoint
uses, so the two cannot drift. Idempotent.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from pricing_baseline import seed_pricing  # noqa: E402


async def main() -> int:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 1
    engine = create_async_engine(url)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    async with sf() as db:
        out = await seed_pricing(db)
    await engine.dispose()
    print(
        f"llm pricing: {out['seeded']} seeded, {out['backfilled']} backfilled, {out['skipped_existing']} already present"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
