"""KB v2 phase 5 — pgvector extension + chunks table."""

from alembic import op

revision = "p6q7r8s9t0u1"
down_revision = "o5p6q7r8s9t0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enable the pgvector extension. Idempotent in Postgres.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    # Chunks table — one row per document chunk, with its 1536-d
    # OpenAI embedding alongside source metadata.
    op.execute("""
        CREATE TABLE IF NOT EXISTS chunks (
            id UUID PRIMARY KEY,
            collection_id UUID NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
            document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            chunk_index INTEGER NOT NULL,
            content TEXT NOT NULL,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            embedding vector(1536),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (document_id, chunk_index)
        );
    """)

    # B-tree on collection_id for the WHERE filter.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_chunks_collection " "ON chunks (collection_id);"
    )
    # Document scoped lookups (delete cascade fast path + per-doc
    # listing).
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_chunks_document " "ON chunks (document_id);"
    )

    op.execute("""
        DO $$
        BEGIN
            BEGIN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_chunks_embedding_hnsw '
                        'ON chunks USING hnsw (embedding vector_cosine_ops) '
                        'WITH (m = 16, ef_construction = 64)';
            EXCEPTION WHEN OTHERS THEN
                BEGIN
                    EXECUTE 'CREATE INDEX IF NOT EXISTS ix_chunks_embedding_ivf '
                            'ON chunks USING ivfflat (embedding vector_cosine_ops) '
                            'WITH (lists = 100)';
                EXCEPTION WHEN OTHERS THEN
                    NULL; -- pgvector unavailable; chunks table still usable for non-vector flows
                END;
            END;
        END $$;
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_chunks_embedding_hnsw;")
    op.execute("DROP INDEX IF EXISTS ix_chunks_embedding_ivf;")
    op.execute("DROP INDEX IF EXISTS ix_chunks_document;")
    op.execute("DROP INDEX IF EXISTS ix_chunks_collection;")
    op.execute("DROP TABLE IF EXISTS chunks;")
    # Don't drop the extension — other tables may use it.
