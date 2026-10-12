"""The default Site broker connection to the in-cluster MQTT broker, and the Machine operators set.

Adds a connection named "Site broker" to the admin's workspace when that
workspace has no telemetry connection yet. Idempotent, safe to re-run.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from models.governance import PermissionSet  # noqa: E402
from models.telemetry import DEFAULT_TOPICS, TelemetryConnection  # noqa: E402
from models.tenant import Tenant  # noqa: E402
from models.user import User  # noqa: E402

NAME = "Site broker"
RAW_TOPICS = ["+/+/can/raw"]
OPERATORS = "Machine operators"
OPERATORS_DESC = (
    "People in this set can send commands to machines over telemetry, such as a "
    "safety hold or a new task. Every command is logged with who sent it and why."
)


def broker_url() -> str:
    url = (os.environ.get("MQTT_URL") or "").strip()
    if url:
        return url
    ns = os.environ.get("POD_NAMESPACE") or "abenix"
    return f"mqtt://abenix-mosquitto.{ns}.svc.cluster.local:1883"


async def main() -> int:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 1
    engine = create_async_engine(url)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    email = os.environ.get("SEED_ADMIN_EMAIL", "admin@abenix.dev")
    async with sf() as db:
        admin = (
            await db.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()
        tenant_id = admin.tenant_id if admin else None
        if tenant_id is None:
            tenant_id = (
                await db.execute(select(Tenant.id).order_by(Tenant.created_at).limit(1))
            ).scalar()
        if tenant_id is None:
            print("no workspace yet, nothing to seed")
            return 0
        for tid in (await db.execute(select(Tenant.id))).scalars().all():
            have_set = (
                await db.execute(
                    select(PermissionSet.id).where(
                        PermissionSet.tenant_id == tid,
                        (PermissionSet.builtin_key == "machine_operators")
                        | (PermissionSet.name == OPERATORS),
                    )
                )
            ).first()
            if have_set is None:
                db.add(
                    PermissionSet(
                        tenant_id=tid,
                        name=OPERATORS,
                        description=OPERATORS_DESC,
                        capabilities=["telemetry.view", "telemetry.command"],
                        builtin_key="machine_operators",
                    )
                )
        have = (
            await db.execute(
                select(func.count())
                .select_from(TelemetryConnection)
                .where(TelemetryConnection.tenant_id == tenant_id)
            )
        ).scalar() or 0
        if have:
            await db.commit()
            print(
                f"{have} telemetry connection(s) already there, Site broker not added"
            )
            return 0
        db.add(
            TelemetryConnection(
                tenant_id=tenant_id,
                name=NAME,
                broker_url=broker_url(),
                topics=list(DEFAULT_TOPICS),
                raw_topics=list(RAW_TOPICS),
                protocol="sparkplug_b",
                enabled=True,
                shared_subscription=False,
                created_by=admin.id if admin else None,
            )
        )
        await db.commit()
        print(f"added {NAME} at {broker_url()}")
    await engine.dispose()
    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        await r.publish("tel:connections:changed", "seed")
        await r.aclose()
    except Exception:  # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
