"""KB v2 deviation fix — hard rename knowledge_bases → knowledge_collections."""
from alembic import op


revision = "r8s9t0u1v2w3"
down_revision = "q7r8s9t0u1v2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The rename. Idempotent guard for re-running on dev DBs that
    # may have already had the rename applied manually. Postgres
    # auto-updates every FK that referenced knowledge_bases(id).
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.tables
                       WHERE table_name = 'knowledge_bases')
               AND NOT EXISTS (SELECT 1 FROM information_schema.tables
                               WHERE table_name = 'knowledge_collections')
            THEN
                ALTER TABLE knowledge_bases RENAME TO knowledge_collections;
            END IF;
        END $$;
    """)


def downgrade() -> None:
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.tables
                       WHERE table_name = 'knowledge_collections')
               AND NOT EXISTS (SELECT 1 FROM information_schema.tables
                               WHERE table_name = 'knowledge_bases')
            THEN
                ALTER TABLE knowledge_collections RENAME TO knowledge_bases;
            END IF;
        END $$;
    """)
