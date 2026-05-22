import asyncio
import json
import os
import sys

sys.path.insert(0, "/app/packages/db")
sys.path.insert(0, "/app/apps/api")
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from models.agent import Agent
from models.execution import Execution


async def main():
    eng = create_async_engine(os.environ["DATABASE_URL"])
    sf = async_sessionmaker(eng, expire_on_commit=False)
    async with sf() as db:
        row = (
            await db.execute(
                select(Execution, Agent.slug)
                .join(Agent)
                .where(Agent.slug == "example_app-metals-extractor", Execution.status == "completed")
                .order_by(desc(Execution.created_at))
                .limit(1)
            )
        ).first()
        if not row:
            print("no completed extractor run")
            return
        r, slug = row
        print(f"{slug} status={r.status} model={r.model_used} dur_ms={r.duration_ms}")
        print(f"--- output_message (first 3000 chars) ---")
        print((r.output_message or "")[:3000])
        print("--- end ---")


asyncio.run(main())
