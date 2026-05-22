"""One-off agent seeder for the precious-metals YAMLs.

Reads the six metals-agent YAML files from stdin (concatenated, separated
by a synthetic delimiter line) and upserts each into the agents table for
the default tenant. Mirrors what packages/db/seeds/seed_agents.py does
without needing the YAMLs on the pod's filesystem.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

sys.path.insert(0, "/app/packages/db")
from models.agent import Agent, AgentStatus, AgentType
from models.tenant import Tenant
from models.user import User


DELIM = "\n---YAML-DELIMITER---\n"


async def main():
    url = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://abenix:abenix@abenix-postgresql:5432/abenix",
    )
    engine = create_async_engine(url, echo=False)
    sf = async_sessionmaker(engine, expire_on_commit=False)

    raw = sys.stdin.read()
    blocks = [b.strip() for b in raw.split(DELIM) if b.strip()]
    print(f"received {len(blocks)} yaml blocks", flush=True)

    async with sf() as db:
        tenant = (
            await db.execute(select(Tenant).order_by(Tenant.created_at).limit(1))
        ).scalar_one_or_none()
        if not tenant:
            print("no tenant rows — abort", flush=True)
            return 1
        admin = (
            await db.execute(
                select(User).where(User.tenant_id == tenant.id, User.email.ilike("admin@%")).limit(1)
            )
        ).scalar_one_or_none()
        if not admin:
            admin = (
                await db.execute(select(User).where(User.tenant_id == tenant.id).limit(1))
            ).scalar_one_or_none()
        if not admin:
            print("no user rows — abort", flush=True)
            return 1
        print(f"tenant={tenant.id} user={admin.id} ({admin.email})", flush=True)

        upserted = 0
        for blk in blocks:
            d = yaml.safe_load(blk)
            slug = d["slug"]
            existing = (
                await db.execute(select(Agent).where(Agent.slug == slug, Agent.tenant_id == tenant.id))
            ).scalar_one_or_none()
            row = existing or Agent()
            row.tenant_id = tenant.id
            row.creator_id = admin.id
            row.name = d["name"]
            row.slug = slug
            row.description = d.get("description") or ""
            row.agent_type = AgentType(d.get("agent_type", "oob"))
            row.category = d.get("category") or "general"
            row.version = d.get("version", "1.0.0")
            row.status = AgentStatus(d.get("status", "active"))
            row.mode = d.get("mode", "agent")
            row.system_prompt = d.get("system_prompt", "")
            row.model_config_ = d.get("model_config") or {}
            row.input_variables = d.get("input_variables") or []
            row.example_prompts = d.get("example_prompts") or []
            row.icon_url = d.get("icon_url")
            if not existing:
                row.id = uuid.uuid4()
                db.add(row)
            upserted += 1
            print(f"  {slug:<48s} {'updated' if existing else 'inserted'}", flush=True)
        await db.commit()
        print(f"done. upserted {upserted}", flush=True)
    await engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
