"""Partitioned chunks DDL and index helpers, shared by API startup, tests and the partition script."""

from __future__ import annotations

import os
import re

SHARED_INDEX = "ix_chunks_embedding_hnsw"
HNSW_WITH = "WITH (m = 16, ef_construction = 64)"
SEARCH_LANGUAGES = (
    "simple",
    "arabic",
    "armenian",
    "basque",
    "catalan",
    "danish",
    "dutch",
    "english",
    "finnish",
    "french",
    "german",
    "greek",
    "hindi",
    "hungarian",
    "indonesian",
    "irish",
    "italian",
    "lithuanian",
    "nepali",
    "norwegian",
    "portuguese",
    "romanian",
    "russian",
    "serbian",
    "spanish",
    "swedish",
    "tamil",
    "turkish",
    "yiddish",
)
INDEX_MODES = ("shared", "deferred", "building", "dedicated")


def partition_count() -> int:
    return max(1, min(1024, int(os.environ.get("KB_CHUNK_PARTITIONS", "32"))))


def storage_type() -> str:
    return "halfvec" if os.environ.get("KB_VECTOR_STORAGE") == "halfvec" else "vector"


def hnsw_ops(column_type: str) -> str:
    return "halfvec_cosine_ops" if column_type == "halfvec" else "vector_cosine_ops"


def version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(p) for p in re.findall(r"\d+", version or "0")[:3])


def partitioned_ddl(
    table: str = "chunks",
    partitions: int | None = None,
    column_type: str | None = None,
) -> list[str]:
    """Hash partitions keep a small collection's rows and index away from a big one."""
    n = partitions or partition_count()
    col = column_type or storage_type()
    out = [
        f"""
        CREATE TABLE {table} (
            id UUID NOT NULL,
            collection_id UUID NOT NULL
                REFERENCES knowledge_collections(id) ON DELETE CASCADE,
            document_id UUID NOT NULL
                REFERENCES documents(id) ON DELETE CASCADE,
            chunk_index INTEGER NOT NULL,
            content TEXT NOT NULL,
            metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            embedding {col}(1536),
            dedicated_index BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            embedding_generation INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (collection_id, id),
            UNIQUE (collection_id, document_id, chunk_index, embedding_generation)
        ) PARTITION BY HASH (collection_id)
        """
    ]
    for i in range(n):
        out.append(
            f"CREATE TABLE {table}_p{i:03d} PARTITION OF {table} "
            f"FOR VALUES WITH (MODULUS {n}, REMAINDER {i})"
        )
    out.append(f"CREATE INDEX ix_{table}_document ON {table} (document_id)")
    return out


DEDICATED_COLUMN = (
    "ALTER TABLE chunks ADD COLUMN IF NOT EXISTS "
    "dedicated_index BOOLEAN NOT NULL DEFAULT FALSE"
)


def effective_storage(pgvector_version: str | None) -> str:
    """halfvec needs pgvector 0.7, an older build keeps full vectors."""
    if storage_type() == "halfvec" and version_tuple(pgvector_version or "") >= (0, 7):
        return "halfvec"
    return "vector"


def shared_hnsw_ddl(table: str = "chunks", column_type: str | None = None) -> str:
    col = column_type or storage_type()
    name = SHARED_INDEX if table == "chunks" else f"ix_{table}_embedding_hnsw"
    return (
        f"CREATE INDEX IF NOT EXISTS {name} ON {table} USING hnsw "
        f"(embedding {hnsw_ops(col)}) {HNSW_WITH} WHERE NOT dedicated_index"
    )


def dedicated_index_name(collection_id: str) -> str:
    return "ix_chunks_kb_" + str(collection_id).replace("-", "")


def dedicated_hnsw_ddl(collection_id: str, table: str, column_type: str) -> str:
    """Only built by the bulk load path, never inside a transaction."""
    return (
        f"CREATE INDEX CONCURRENTLY IF NOT EXISTS "
        f"{dedicated_index_name(collection_id)} ON {table} USING hnsw "
        f"(embedding {hnsw_ops(column_type)}) {HNSW_WITH} "
        f"WHERE collection_id = '{collection_id}' AND dedicated_index"
    )


# one row of facts about the live table, used by both startup paths
STATE_SQL = """
SELECT c.relkind::text,
       (SELECT format_type(a.atttypid, a.atttypmod) FROM pg_attribute a
         WHERE a.attrelid = c.oid AND a.attname = 'embedding'),
       (SELECT extversion FROM pg_extension WHERE extname = 'vector'),
       EXISTS (SELECT 1 FROM pg_indexes i
                WHERE i.tablename = 'chunks'
                  AND i.indexname = 'ix_chunks_embedding_hnsw'
                  AND i.indexdef ILIKE '%WHERE%dedicated_index%')
  FROM pg_class c
 WHERE c.oid = to_regclass('chunks')
"""


def column_base_type(formatted: str | None) -> str:
    return "halfvec" if (formatted or "").startswith("halfvec") else "vector"


def validate_language(language: str | None) -> str:
    return language if language in SEARCH_LANGUAGES else "simple"


def startup_plan(relkind: str | None, pgvector_version: str | None) -> list[str]:
    """New installs partition, an existing table stays as it is until an operator moves it."""
    if relkind is None:
        return partitioned_ddl(column_type=effective_storage(pgvector_version))
    if relkind == "r":
        from chunks_schema import startup_statements

        return [*startup_statements(), DEDICATED_COLUMN]
    return []


def hnsw_plan(relkind: str | None, column_type: str | None) -> str:
    if relkind == "p":
        return shared_hnsw_ddl(column_type=column_base_type(column_type))
    return (
        f"CREATE INDEX IF NOT EXISTS {SHARED_INDEX} "
        "ON chunks USING hnsw (embedding vector_cosine_ops)"
    )
