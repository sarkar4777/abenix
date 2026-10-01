"""Backfill agent grants for knowledge bases that were bound by agent_id only.

Before the grant was written at creation, a knowledge base created with an
agent_id carried the binding on the row and nowhere else. The runtime decides
whether to register knowledge_search from agent_collection_grants, so those
agents answered that they had no search tool. This adds the missing READ grant
for every such pair. Idempotent, safe to re-run.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from models.collection_grant import (
    AgentCollectionGrant,
    CollectionPermission,
)  # noqa: E402
from models.knowledge_base import KnowledgeBase  # noqa: E402


async def main() -> int:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 1
    engine = create_async_engine(url)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    added = 0
    async with sf() as db:
        bound = (
            (
                await db.execute(
                    select(KnowledgeBase).where(KnowledgeBase.agent_id.isnot(None))
                )
            )
            .scalars()
            .all()
        )
        for kb in bound:
            have = (
                await db.execute(
                    select(AgentCollectionGrant).where(
                        AgentCollectionGrant.agent_id == kb.agent_id,
                        AgentCollectionGrant.collection_id == kb.id,
                    )
                )
            ).scalar_one_or_none()
            if have is not None:
                continue
            db.add(
                AgentCollectionGrant(
                    agent_id=kb.agent_id,
                    collection_id=kb.id,
                    permission=CollectionPermission.READ,
                    granted_by=kb.created_by,
                )
            )
            added += 1
        await db.commit()
    await engine.dispose()
    print(f"kb agent grants: {len(bound)} bound knowledge bases, {added} grants added")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
