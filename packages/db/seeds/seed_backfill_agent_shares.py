"""Copy legacy agent_shares rows into resource_shares.

The sharing routes used to write agent_shares while the list and access
checks read resource_shares, so grants made through the old dialog never
took effect. This moves them over. Idempotent, safe to re-run. The old
table is left in place.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from models.agent import Agent  # noqa: E402
from models.agent_share import AgentShare  # noqa: E402
from models.resource_share import ResourceShare, SharePermission  # noqa: E402

_PERM = {
    "view": SharePermission.VIEW,
    "execute": SharePermission.EXECUTE,
    "edit": SharePermission.EDIT,
}


async def main() -> int:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 1
    engine = create_async_engine(url)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    added = skipped = 0
    async with sf() as db:
        rows = (
            await db.execute(
                select(AgentShare, Agent)
                .join(Agent, Agent.id == AgentShare.agent_id)
                .where(AgentShare.shared_with_user_id.isnot(None))
            )
        ).all()
        for legacy, agent in rows:
            have = (
                await db.execute(
                    select(ResourceShare.id).where(
                        ResourceShare.resource_type == "agent",
                        ResourceShare.resource_id == legacy.agent_id,
                        ResourceShare.shared_with_user_id == legacy.shared_with_user_id,
                    )
                )
            ).first()
            if have is not None:
                skipped += 1
                continue
            raw = (
                legacy.permission.value
                if hasattr(legacy.permission, "value")
                else str(legacy.permission)
            )
            db.add(
                ResourceShare(
                    tenant_id=agent.tenant_id,
                    resource_type="agent",
                    resource_id=legacy.agent_id,
                    shared_with_user_id=legacy.shared_with_user_id,
                    shared_with_email=legacy.shared_with_email,
                    permission=_PERM.get(raw.lower(), SharePermission.VIEW),
                    shared_by=legacy.shared_by,
                )
            )
            added += 1
        await db.commit()
    await engine.dispose()
    print(
        f"agent share backfill: {len(rows)} legacy rows, {added} copied, {skipped} already present"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
