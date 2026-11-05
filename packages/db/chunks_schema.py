"""DDL for an unpartitioned chunks table, shared by API startup and tests."""

from __future__ import annotations

GENERATION_COLUMN = (
    "ALTER TABLE chunks ADD COLUMN IF NOT EXISTS "
    "embedding_generation INTEGER NOT NULL DEFAULT 0"
)
UNIQUE_BY_GENERATION = (
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_chunks_doc_index_generation "
    "ON chunks (document_id, chunk_index, embedding_generation)"
)
COLLECTION_GENERATION = (
    "CREATE INDEX IF NOT EXISTS ix_chunks_collection_generation "
    "ON chunks (collection_id, embedding_generation)"
)
DROP_OLD_UNIQUE = (
    "ALTER TABLE chunks DROP CONSTRAINT IF EXISTS chunks_document_id_chunk_index_key"
)

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS chunks (
    id UUID PRIMARY KEY,
    collection_id UUID NOT NULL
        REFERENCES knowledge_collections(id) ON DELETE CASCADE,
    document_id UUID NOT NULL
        REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    embedding vector(1536),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    embedding_generation INTEGER NOT NULL DEFAULT 0
)
"""


def startup_statements() -> list[str]:
    """Idempotent, a database the migration already reached does nothing here."""
    return [
        CREATE_TABLE,
        GENERATION_COLUMN,
        UNIQUE_BY_GENERATION,
        DROP_OLD_UNIQUE,
        COLLECTION_GENERATION,
        "CREATE INDEX IF NOT EXISTS ix_chunks_collection ON chunks (collection_id)",
        "CREATE INDEX IF NOT EXISTS ix_chunks_document ON chunks (document_id)",
    ]
