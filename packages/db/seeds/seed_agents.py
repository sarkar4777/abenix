"""Seed script to insert OOB agents into the database."""
from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models.agent import Agent, AgentStatus, AgentType
from models.tenant import Tenant
from models.user import User

import os

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://abenix:abenix@localhost:5432/abenix",
)
SEEDS_DIR = Path(__file__).parent / "agents"

SHARED_TENANT_NAME = "Abenix"
SHARED_TENANT_SLUG = "abenix"
LEGACY_SYSTEM_TENANT_SLUG = "abenix-system"
SYSTEM_USER_EMAIL = "system@abenix.dev"

# Agents we once seeded but no longer ship. When the seeder runs against
# an older DB, these get archived instead of left dangling. Keeps the
# agent catalog honest across upgrades without a manual migration step.
RETIRED_SLUGS: set[str] = {
    # Migration / Exasol→BigQuery stubs — orphaned without MCPs we never ship
    "cache-manager",
    "query-router",
    "validation-agent",
    "migration-observatory",
    "migration-pipeline",
    "data-mover",
    "sql-transformer",
    "schema-architect",
    "report-migrator",
    # Testing artifacts that never belonged in the user-visible palette
    "generic-stress-test",
    # Replaced by the Industrial IoT suite (iot-pump-* / iot-coldchain-*)
    "iot-sensor-monitor",
    "predictive-maintenance",
    "supply-chain-risk-monitor",
}


async def _migrate_legacy_system_tenant(
    db: AsyncSession, target_tenant: Tenant,
) -> None:
    """Move every resource off the legacy 'abenix-system' tenant."""
    legacy = (await db.execute(
        select(Tenant).where(Tenant.slug == LEGACY_SYSTEM_TENANT_SLUG)
    )).scalar_one_or_none()
    if legacy is None or legacy.id == target_tenant.id:
        return

    from sqlalchemy import text as _t
    moves = 0
    # Move every tenant-scoped resource. The list mirrors models with
    # tenant_id columns; new tenant-scoped tables added later just
    # need one more line here.
    for table in (
        "agents", "executions", "knowledge_collections",
        "knowledge_projects", "cognify_jobs", "graph_entities",
        "retrieval_feedback", "retrieval_metrics",
        "ml_models", "code_assets", "saved_tools",
        "portfolio_schemas", "agent_memories", "moderation_policies",
        "moderation_events", "agent_triggers", "pipeline_states",
        "drift_alerts", "webhooks", "webhook_deliveries",
        "batch_jobs", "workspaces", "memory_palace_entries",
        "user_token_quotas", "subject_policies",
    ):
        try:
            r = await db.execute(_t(
                f"UPDATE {table} SET tenant_id = :new "
                f"WHERE tenant_id = :old"
            ).bindparams(new=target_tenant.id, old=legacy.id))
            moves += r.rowcount or 0
        except Exception:
            # Some tables may not exist in older DBs — skip silently.
            pass

    # Move users too — the system@abenix.dev account stays alive
    # but joins the unified tenant.
    try:
        await db.execute(_t(
            "UPDATE users SET tenant_id = :new WHERE tenant_id = :old"
        ).bindparams(new=target_tenant.id, old=legacy.id))
    except Exception:
        pass

    # Drop the now-empty legacy tenant. Safe — every FK was repointed.
    try:
        await db.delete(legacy)
        print(f"  Migrated {moves} resources off legacy 'Abenix System' tenant and removed it.")
    except Exception as e:
        print(f"  Could not delete legacy tenant (non-fatal): {e}")


async def ensure_shared_tenant(db: AsyncSession) -> tuple[Tenant, User]:
    """Find-or-create the single shared 'Abenix' tenant."""
    from models.tenant import TenantPlan
    tenant = (await db.execute(
        select(Tenant).where(Tenant.name == SHARED_TENANT_NAME)
    )).scalar_one_or_none()

    if tenant is None:
        tenant = Tenant(
            name=SHARED_TENANT_NAME,
            slug=SHARED_TENANT_SLUG,
            plan=TenantPlan.BUSINESS,
        )
        db.add(tenant)
        await db.flush()
        print(f"  Created shared tenant: {SHARED_TENANT_NAME}")
    else:
        # Upgrade the legacy free-plan tenant — the unified tenant
        # holds platform agents, so it must not throttle.
        if tenant.plan == TenantPlan.FREE:
            tenant.plan = TenantPlan.BUSINESS

    # One-shot consolidation of any pre-existing legacy split.
    await _migrate_legacy_system_tenant(db, tenant)

    system_user = (await db.execute(
        select(User).where(User.email == SYSTEM_USER_EMAIL)
    )).scalar_one_or_none()

    if system_user is None:
        import bcrypt
        system_user = User(
            tenant_id=tenant.id,
            email=SYSTEM_USER_EMAIL,
            password_hash=bcrypt.hashpw(uuid.uuid4().hex.encode(), bcrypt.gensalt()).decode(),
            full_name="Abenix System",
            role="ADMIN",
            is_active=True,
        )
        db.add(system_user)
        await db.flush()
    elif system_user.tenant_id != tenant.id:
        # Re-home the system user if it was created in the legacy
        # tenant before consolidation.
        system_user.tenant_id = tenant.id

    return tenant, system_user


# Backwards-compat alias — older seed runners may import the old name.
ensure_system_tenant = ensure_shared_tenant


async def seed_agents() -> None:
    engine = create_async_engine(DATABASE_URL, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as db:
        tenant, system_user = await ensure_shared_tenant(db)

        yaml_files = sorted(SEEDS_DIR.glob("*.yaml"))
        if not yaml_files:
            print("No seed files found.")
            return

        for yaml_file in yaml_files:
            with open(yaml_file, encoding="utf-8") as f:
                data = yaml.safe_load(f)

            slug = data["slug"]
            result = await db.execute(select(Agent).where(Agent.slug == slug))
            existing = result.scalar_one_or_none()

            model_cfg = dict(data.get("model_config", {}))
            # Fallback: pick up top-level model/temperature/tools if not in model_config
            if "model" not in model_cfg and data.get("model"):
                model_cfg["model"] = data["model"]
            if "temperature" not in model_cfg and data.get("temperature") is not None:
                model_cfg["temperature"] = data["temperature"]
            if "tools" not in model_cfg and data.get("tools"):
                model_cfg["tools"] = data["tools"]
            if "max_iterations" not in model_cfg and data.get("max_iterations"):
                model_cfg["max_iterations"] = data["max_iterations"]
            if data.get("mcp_extensions"):
                model_cfg["mcp_extensions"] = data["mcp_extensions"]
            if data.get("mode"):
                model_cfg["mode"] = data["mode"]
            if data.get("pipeline_config"):
                model_cfg["pipeline_config"] = data["pipeline_config"]
            if data.get("input_variables"):
                model_cfg["input_variables"] = data["input_variables"]
            if data.get("example_prompts"):
                model_cfg["example_prompts"] = data["example_prompts"]
            # Per-tool configuration: usage_instructions, parameter_defaults,
            # max_calls, require_approval. Enables YAML authors to declare
            # "this agent needs a code_asset tool pinned to asset X" without
            # editing the agent via the API later.
            if data.get("tool_config"):
                model_cfg["tool_config"] = data["tool_config"]
            if data.get("max_tokens"):
                model_cfg["max_tokens"] = data["max_tokens"]

            icon = data.get("icon")

            rp = str(data.get("runtime_pool") or "default").strip().lower()
            # Heuristic: any agent whose slug contains "chat" stays
            # inline unless the yaml explicitly says otherwise. Chat is
            # where the extra 200-400ms queue hop hurts UX the most.
            if "runtime_pool" not in data and "chat" in slug.lower():
                rp = "inline"
            scaling_kwargs = dict(
                runtime_pool=rp,
                min_replicas=int(data.get("min_replicas", 0 if rp == "inline" else 1)),
                max_replicas=int(data.get("max_replicas", 1 if rp == "inline" else 10)),
                concurrency_per_replica=int(data.get("concurrency_per_replica", 1 if rp == "inline" else 3)),
                rate_limit_qps=data.get("rate_limit_qps"),
                daily_budget_usd=data.get("daily_budget_usd"),
            )

            if existing:
                print(f"  Updating: {data['name']} ({slug}) [{rp}]")
                existing.name = data["name"]
                existing.description = data.get("description", "")
                existing.system_prompt = data.get("system_prompt", "")
                existing.model_config_ = model_cfg
                existing.category = data.get("category")
                existing.version = data.get("version", "1.0.0")
                existing.status = AgentStatus(data.get("status", "active"))
                existing.icon_url = icon
                for k, v in scaling_kwargs.items():
                    setattr(existing, k, v)
            else:
                print(f"  Creating: {data['name']} ({slug}) [{rp}]")
                agent = Agent(
                    tenant_id=tenant.id,
                    creator_id=system_user.id,
                    name=data["name"],
                    slug=slug,
                    description=data.get("description", ""),
                    system_prompt=data.get("system_prompt", ""),
                    model_config_=model_cfg,
                    agent_type=AgentType(data.get("agent_type", "oob").lower()),
                    category=data.get("category"),
                    version=data.get("version", "1.0.0"),
                    status=AgentStatus(data.get("status", "active").lower()),
                    icon_url=icon,
                    **scaling_kwargs,
                )
                db.add(agent)

        # Retire agents we no longer ship — archive, don't delete, so
        # historical executions keep their FK target.
        if RETIRED_SLUGS:
            res = await db.execute(select(Agent).where(Agent.slug.in_(RETIRED_SLUGS)))
            retired_rows = list(res.scalars())
            for a in retired_rows:
                if a.status != AgentStatus.ARCHIVED:
                    print(f"  Archiving retired: {a.name} ({a.slug})")
                    a.status = AgentStatus.ARCHIVED
            await db.commit()

        await db.commit()
        print("Seed complete.")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed_agents())
