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
                .where(Agent.slug.like("example_app-metals-%"))
                .order_by(desc(Execution.created_at))
                .limit(8)
            )
        ).all()
        for r, slug in rows:
            ol = len(r.output_message or "")
            tc = len(r.tool_calls or [])
            print(f"{slug:<46s} {r.status:<10s} tools={tc} out_len={ol} dur_ms={r.duration_ms}")
            if r.output_message:
                try:
                    parsed = json.loads(r.output_message)
                    keys_with_vals = sum(1 for v in parsed.values() if v not in (None, "", [], {}))
                    print(f"  parsed: {len(parsed)} keys, {keys_with_vals} populated")
                    sample = {k: v for k, v in list(parsed.items())[:6]}
                    print(f"  sample: {json.dumps(sample, default=str)[:200]}")
                except Exception:
                    snippet = (r.output_message or "")[:120]
                    print(f"  not-json: {snippet!r}")
            if r.tool_calls:
                tools_used = [tc.get("tool_name") or tc.get("name") for tc in (r.tool_calls or [])[:8]]
                print(f"  tools_used: {tools_used}")


asyncio.run(main())
