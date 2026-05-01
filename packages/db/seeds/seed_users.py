"""Seed default user accounts and service API keys for development."""
import asyncio
import hashlib
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from models.tenant import Tenant, TenantPlan
from models.user import User, UserRole
from models.api_key import ApiKey

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://abenix:abenix@localhost:5432/abenix",
)

engine = create_async_engine(DATABASE_URL)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# All default users share one tenant
SHARED_TENANT_NAME = "Abenix"

ACCOUNTS = [
    {
        "email": "admin@abenix.dev",
        "password": "Admin123456",
        "full_name": "Admin User",
        "role": UserRole.ADMIN,
    },
    {
        "email": "demo@abenix.dev",
        "password": "Demo123456",
        "full_name": "Demo User",
        "role": UserRole.USER,
    },
]


def _hash_password(password: str) -> str:
    """Hash password with bcrypt."""
    import bcrypt
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


async def seed_users():
    async with async_session() as db:
        # Find or create the shared tenant
        result = await db.execute(select(Tenant).where(Tenant.name == SHARED_TENANT_NAME))
        shared_tenant = result.scalar_one_or_none()

        if not shared_tenant:
            shared_tenant = Tenant(
                id=uuid.uuid4(),
                name=SHARED_TENANT_NAME,
                slug="abenix-" + uuid.uuid4().hex[:6],
                plan=TenantPlan.BUSINESS,  # Unlimited daily executions for dev/demo
            )
            db.add(shared_tenant)
            await db.flush()
            print(f"  Created shared tenant: {SHARED_TENANT_NAME} (plan=business, unlimited)")
        else:
            # Upgrade existing tenant to business if on free plan
            if shared_tenant.plan == TenantPlan.FREE:
                shared_tenant.plan = TenantPlan.BUSINESS
                print(f"  Upgraded shared tenant to business plan (unlimited executions)")
            else:
                print(f"  Shared tenant exists: {SHARED_TENANT_NAME} ({shared_tenant.id})")

        for acct in ACCOUNTS:
            result = await db.execute(select(User).where(User.email == acct["email"]))
            existing = result.scalar_one_or_none()
            if existing:
                # Migrate existing user to shared tenant if needed
                if str(existing.tenant_id) != str(shared_tenant.id):
                    existing.tenant_id = shared_tenant.id
                    print(f"  Migrated: {acct['email']} -> shared tenant")
                else:
                    print(f"  Exists: {acct['email']}")
                continue

            user = User(
                id=uuid.uuid4(),
                email=acct["email"],
                password_hash=_hash_password(acct["password"]),
                full_name=acct["full_name"],
                role=acct["role"],
                tenant_id=shared_tenant.id,
                is_active=True,
            )
            db.add(user)
            print(f"  Created: {acct['email']} / {acct['password']} ({acct['role'].value})")

        # These keys let the example app and Saudi Tourism call the Abenix API.
        # Read from .env file directly (env vars may not be set on Windows).
        env_vals: dict[str, str] = {}
        env_file = Path(__file__).resolve().parents[2] / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    env_vals[k.strip()] = v.strip()

        admin_result = await db.execute(select(User).where(User.email == "admin@abenix.dev"))
        admin_user = admin_result.scalar_one_or_none()
        if admin_user:
            SERVICE_KEYS = [
                {
                    "name": "example_app-service",
                    "env_var": "EXAMPLE_APP_ABENIX_API_KEY",
                },
                {
                    "name": "sauditourism-service",
                    "env_var": "SAUDITOURISM_ABENIX_API_KEY",
                },
            ]
            for svc in SERVICE_KEYS:
                raw_key = os.environ.get(svc["env_var"], "") or env_vals.get(svc["env_var"], "")
                if not raw_key:
                    continue
                key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
                prefix = raw_key[:8] + "****" + raw_key[-4:]

                # Check if this key already exists
                existing = await db.execute(
                    select(ApiKey).where(ApiKey.key_hash == key_hash)
                )
                if existing.scalar_one_or_none():
                    print(f"  API key exists: {svc['name']} ({prefix})")
                    continue

                api_key = ApiKey(
                    id=uuid.uuid4(),
                    user_id=admin_user.id,
                    tenant_id=shared_tenant.id,
                    name=svc["name"],
                    key_hash=key_hash,
                    key_prefix=prefix,
                    is_active=True,
                    scopes={"allowed_actions": ["execute", "list", "delegate", "can_delegate"]},
                )
                db.add(api_key)
                print(f"  Created API key: {svc['name']} ({prefix})")

        await db.commit()
    await engine.dispose()


if __name__ == "__main__":
    print("Seeding default user accounts...")
    asyncio.run(seed_users())
    print("Done.")
