"""Seed subject policies + ensure subject_policies table exists."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

# Ensure we can import models
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def ensure_table_and_seed():
    import asyncpg

    db_url = os.environ.get(
        "DATABASE_URL", "postgresql://abenix:abenix@localhost:5432/abenix"
    )
    # Strip async driver prefix if present
    db_url = db_url.replace("postgresql+asyncpg://", "postgresql://")

    conn = await asyncpg.connect(db_url)

    # Step 1: Create table if not exists (idempotent)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS subject_policies (
            id UUID PRIMARY KEY,
            api_key_id UUID NOT NULL REFERENCES api_keys(id) ON DELETE CASCADE,
            subject_type VARCHAR(50) NOT NULL,
            subject_id VARCHAR(255) NOT NULL,
            display_name VARCHAR(255),
            description VARCHAR(500),
            rules JSONB DEFAULT '{}'::jsonb,
            is_active BOOLEAN DEFAULT true,
            last_used_at TIMESTAMP WITH TIME ZONE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT now()
        );
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_subject_policies_lookup ON subject_policies(api_key_id, subject_type, subject_id);"
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_subject_policies_api_key ON subject_policies(api_key_id);"
    )
    print("  Ensured subject_policies table exists")

    # Step 2: Find the the example app platform key
    ciq_key = await conn.fetchrow(
        "SELECT id FROM api_keys WHERE name = 'the example app Platform Key' AND is_active = true LIMIT 1"
    )

    if not ciq_key:
        print("  No the example app platform key found — skipping default policy seeding")
        await conn.close()
        return

    # Step 3: Seed wildcard default policy for all the example app subjects
    # Each subject (example_app user) gets their own scoped access via templates.
    existing = await conn.fetchrow(
        """
        SELECT id FROM subject_policies
        WHERE api_key_id = $1 AND subject_type = 'example_app' AND subject_id = '*'
    """,
        ciq_key["id"],
    )

    default_rules = {
        "agents": {
            "mode": "allowlist",
            "slugs": [
                "example_app-chat",
                "example_app-pipeline",
                "example_app-deep-extractor",
            ],
        },
        "knowledge_bases": [
            {
                "kb_id": "*",
                "access_mode": "namespace",
                "namespace_pattern": "example_app-{subject_id}",
                "allowed_actions": ["read", "search"],
            }
        ],
        "tools": {
            "mode": "allowlist",
            "names": [
                "portfolio_example_app",
                "knowledge_search",
                "knowledge_store",
                "graph_explorer",
                "contract_search",
                "ppa_calculator",
                "entso_e",
                "ember_climate",
                "ecb_rates",
            ],
        },
        "data_scopes": {
            "example_app.contracts.user_id": "{subject_id}",
        },
        "denied_actions": ["delete", "admin"],
    }

    if existing:
        await conn.execute(
            """
            UPDATE subject_policies SET
                display_name = $1,
                description = $2,
                rules = $3::jsonb,
                updated_at = NOW()
            WHERE id = $4
        """,
            "the example app Default (All Users)",
            "Default policy for all the example app users — isolates access to own data",
            json.dumps(default_rules),
            existing["id"],
        )
        print("  Updated default the example app policy")
    else:
        await conn.execute(
            """
            INSERT INTO subject_policies
            (id, api_key_id, subject_type, subject_id, display_name, description, rules, is_active, created_at, updated_at)
            VALUES ($1, $2, 'example_app', '*', $3, $4, $5::jsonb, true, NOW(), NOW())
        """,
            uuid.uuid4(),
            ciq_key["id"],
            "the example app Default (All Users)",
            "Default policy for all the example app users — isolates access to own data",
            json.dumps(default_rules),
        )
        print("  Seeded default the example app policy")

    await conn.close()


def main():
    try:
        asyncio.run(ensure_table_and_seed())
        print("Subject policy seeding complete.")
    except Exception as e:
        print(f"Subject policy seeding failed: {e}")
        # Don't fail the whole startup if this errors
        return


if __name__ == "__main__":
    main()
