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
        rows = (
            await db.execute(
                select(Execution, Agent.slug)
                .join(Agent)
                .where(Agent.slug.like("contractiq-metals-%"))
                .order_by(desc(Execution.created_at))
                .limit(5)
            )
        ).all()
        for r, slug in rows:
            print(f"{slug:<46s} {r.status}  failure_code={r.failure_code}")
            print(f"  error_message: {(r.error_message or '')[:300]!r}")
            print(f"  model_used: {r.model_used}")


asyncio.run(main())
