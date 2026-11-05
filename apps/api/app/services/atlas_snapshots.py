"""Atlas snapshots as row versions. A snapshot stores what changed since the last one."""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import desc, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from models.atlas import AtlasGraph, AtlasSnapshot  # type: ignore

logger = logging.getLogger(__name__)

KEEP_AUTO = int(os.environ.get("ATLAS_SNAPSHOT_KEEP_AUTO", "50"))
FORMAT_DIFF = "diff"
# a transaction that began before the last snapshot can commit after it
OVERLAP = timedelta(minutes=2)
# the first snapshot copies the graph, past this it does not hold up an edit
BASELINE_INLINE_NODES = int(os.environ.get("ATLAS_BASELINE_INLINE_NODES", "2000"))

NODE_PAYLOAD = """jsonb_build_object(
    'id', id, 'graph_id', graph_id, 'label', label, 'kind', kind::text,
    'description', description, 'properties', properties,
    'position_x', position_x, 'position_y', position_y,
    'document_id', document_id, 'source', source, 'confidence', confidence,
    'tags', tags, 'valid_from', valid_from, 'valid_to', valid_to,
    'recorded_at', recorded_at, 'source_anchors', source_anchors,
    'created_at', created_at)"""

EDGE_PAYLOAD = """jsonb_build_object(
    'id', id, 'graph_id', graph_id, 'from_node_id', from_node_id,
    'to_node_id', to_node_id, 'label', label, 'description', description,
    'cardinality_from', cardinality_from, 'cardinality_to', cardinality_to,
    'inverse_edge_id', inverse_edge_id, 'is_directed', is_directed,
    'properties', properties, 'source', source, 'confidence', confidence,
    'valid_from', valid_from, 'valid_to', valid_to,
    'recorded_at', recorded_at, 'source_anchors', source_anchors,
    'created_at', created_at)"""

LATEST_STATE = """
SELECT DISTINCT ON (kind, row_id) kind, row_id, deleted, payload
FROM atlas_snapshot_rows
WHERE graph_id = :g AND version <= :v
ORDER BY kind, row_id, version DESC
"""


LABEL_SEARCH_STATEMENTS = (
    "CREATE EXTENSION IF NOT EXISTS pg_trgm",
    "CREATE INDEX IF NOT EXISTS ix_atlas_nodes_label_trgm ON atlas_nodes "
    "USING gin (lower(label) gin_trgm_ops)",
)


def is_diff(snapshot: Any) -> bool:
    return isinstance(snapshot.payload, dict) and (
        snapshot.payload.get("format") == FORMAT_DIFF
    )


async def _copy_rows(
    db: AsyncSession, graph_id: uuid.UUID, version: int, since: datetime | None
) -> int:
    changed = "AND updated_at >= :since" if since is not None else ""
    params: dict[str, Any] = {"g": graph_id, "v": version}
    if since is not None:
        params["since"] = since - OVERLAP
    total = 0
    for kind, table, payload in (
        ("n", "atlas_nodes", NODE_PAYLOAD),
        ("e", "atlas_edges", EDGE_PAYLOAD),
    ):
        result = await db.execute(
            text(
                f"""
                INSERT INTO atlas_snapshot_rows (graph_id, kind, row_id, version, deleted, payload)
                SELECT graph_id, '{kind}', id, :v, false, {payload}
                FROM {table} WHERE graph_id = :g {changed}
                ON CONFLICT DO NOTHING
                """
            ),
            params,
        )
        total += result.rowcount or 0
    return total


async def _mark_removed(db: AsyncSession, graph_id: uuid.UUID, version: int) -> int:
    result = await db.execute(
        text(
            f"""
            INSERT INTO atlas_snapshot_rows (graph_id, kind, row_id, version, deleted, payload)
            SELECT :g, s.kind, s.row_id, :v, true, NULL
            FROM ({LATEST_STATE}) s
            WHERE NOT s.deleted
              AND NOT EXISTS (SELECT 1 FROM atlas_nodes n WHERE s.kind = 'n' AND n.id = s.row_id)
              AND NOT EXISTS (SELECT 1 FROM atlas_edges e WHERE s.kind = 'e' AND e.id = s.row_id)
            ON CONFLICT DO NOTHING
            """
        ),
        {"g": graph_id, "v": version},
    )
    return result.rowcount or 0


async def capture(
    db: AsyncSession,
    graph: AtlasGraph,
    user_id: uuid.UUID | None,
    label: str | None = None,
    auto: bool = True,
    meta: dict[str, Any] | None = None,
) -> AtlasSnapshot:
    """Save the graph at its current version, at the cost of the rows that changed."""
    await db.flush()
    version = graph.version
    existing = (
        await db.execute(
            select(AtlasSnapshot).where(
                AtlasSnapshot.graph_id == graph.id, AtlasSnapshot.version == version
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if not auto:
            existing.auto = False
            existing.label = label or existing.label
        return existing

    last_at = (
        await db.execute(
            text(
                "SELECT max(s.created_at) FROM atlas_snapshots s "
                "WHERE s.graph_id = :g AND s.payload->>'format' = :f"
            ),
            {"g": graph.id, "f": FORMAT_DIFF},
        )
    ).scalar()
    changed = await _copy_rows(db, graph.id, version, last_at)
    removed = await _mark_removed(db, graph.id, version) if last_at else 0
    snapshot = AtlasSnapshot(
        id=uuid.uuid4(),
        graph_id=graph.id,
        version=version,
        label=label,
        created_by=user_id,
        auto=auto,
        payload={
            "format": FORMAT_DIFF,
            "graph": meta or {},
            "changed": changed,
            "removed": removed,
            "baseline": last_at is None,
        },
    )
    db.add(snapshot)
    await db.flush()
    await prune(db, graph.id)
    return snapshot


async def prune(db: AsyncSession, graph_id: uuid.UUID, keep: int = KEEP_AUTO) -> int:
    """Drop old automatic snapshots, then the row versions no snapshot can reach."""
    result = await db.execute(
        text(
            """
            DELETE FROM atlas_snapshots WHERE id IN (
                SELECT id FROM atlas_snapshots
                WHERE graph_id = :g AND auto
                ORDER BY created_at DESC OFFSET :keep)
            """
        ),
        {"g": graph_id, "keep": keep},
    )
    removed = result.rowcount or 0
    if removed:
        await db.execute(
            text(
                """
                DELETE FROM atlas_snapshot_rows r USING (
                    SELECT kind, row_id, version,
                           lead(version) OVER (PARTITION BY kind, row_id ORDER BY version) AS next
                    FROM atlas_snapshot_rows WHERE graph_id = :g
                ) w
                WHERE r.graph_id = :g AND r.kind = w.kind AND r.row_id = w.row_id
                  AND r.version = w.version
                  AND NOT EXISTS (
                    SELECT 1 FROM atlas_snapshots s
                    WHERE s.graph_id = :g AND s.version >= w.version
                      AND (w.next IS NULL OR s.version < w.next))
                """
            ),
            {"g": graph_id},
        )
    return removed


async def maybe_capture(
    db: AsyncSession,
    graph: AtlasGraph,
    user_id: uuid.UUID,
    label: str | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    """Automatic snapshots at most once a minute per graph."""
    last = (
        await db.execute(
            select(AtlasSnapshot.created_at)
            .where(AtlasSnapshot.graph_id == graph.id)
            .order_by(desc(AtlasSnapshot.created_at))
            .limit(1)
        )
    ).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if last and (now - last) < timedelta(seconds=60):
        return
    if (graph.node_count or 0) > BASELINE_INLINE_NODES and not await _has_rows(
        db, graph.id
    ):
        _baseline_later(graph.id, user_id, label, meta)
        return
    await capture(db, graph, user_id, label=label, auto=label is None, meta=meta)


async def _has_rows(db: AsyncSession, graph_id: uuid.UUID) -> bool:
    found = await db.execute(
        text("SELECT 1 FROM atlas_snapshot_rows WHERE graph_id = :g LIMIT 1"),
        {"g": graph_id},
    )
    return found.first() is not None


_BASELINE_TASKS: dict[uuid.UUID, asyncio.Task] = {}


def _baseline_later(
    graph_id: uuid.UUID,
    user_id: uuid.UUID,
    label: str | None,
    meta: dict[str, Any] | None,
) -> None:
    if graph_id in _BASELINE_TASKS:
        return

    async def run() -> None:
        from app.core.deps import bg_session

        try:
            # after the edit that asked for this has committed
            await asyncio.sleep(0.2)
            async with bg_session() as db:
                graph = (
                    await db.execute(
                        select(AtlasGraph).where(AtlasGraph.id == graph_id)
                    )
                ).scalar_one()
                await capture(
                    db, graph, user_id, label=label, auto=label is None, meta=meta
                )
                await db.commit()
        except Exception as e:
            logger.warning("atlas baseline snapshot failed for %s: %s", graph_id, e)
        finally:
            _BASELINE_TASKS.pop(graph_id, None)

    _BASELINE_TASKS[graph_id] = asyncio.create_task(run())


RESTORE_NODES = """
INSERT INTO atlas_nodes (id, graph_id, label, kind, description, properties,
    position_x, position_y, document_id, source, confidence, tags,
    valid_from, valid_to, recorded_at, source_anchors, created_at, updated_at)
SELECT s.row_id, :g, s.payload->>'label',
    CAST(s.payload->>'kind' AS atlas_node_kind), coalesce(s.payload->>'description', ''),
    coalesce(s.payload->'properties', '{}'::jsonb),
    (s.payload->>'position_x')::float, (s.payload->>'position_y')::float,
    d.id, coalesce(s.payload->>'source', 'user'), (s.payload->>'confidence')::float,
    coalesce(s.payload->'tags', '[]'::jsonb),
    (s.payload->>'valid_from')::timestamptz, (s.payload->>'valid_to')::timestamptz,
    coalesce((s.payload->>'recorded_at')::timestamptz, now()),
    NULLIF(s.payload->'source_anchors', 'null'::jsonb),
    coalesce((s.payload->>'created_at')::timestamptz, now()), now()
FROM atlas_restore_state s
LEFT JOIN documents d ON d.id = (s.payload->>'document_id')::uuid
WHERE s.kind = 'n' AND NOT s.deleted
  AND NOT EXISTS (SELECT 1 FROM atlas_nodes l
                  WHERE l.id = s.row_id AND l.updated_at < :since)
ON CONFLICT (id) DO UPDATE SET
    label = EXCLUDED.label, kind = EXCLUDED.kind, description = EXCLUDED.description,
    properties = EXCLUDED.properties, position_x = EXCLUDED.position_x,
    position_y = EXCLUDED.position_y, document_id = EXCLUDED.document_id,
    source = EXCLUDED.source, confidence = EXCLUDED.confidence, tags = EXCLUDED.tags,
    valid_from = EXCLUDED.valid_from, valid_to = EXCLUDED.valid_to,
    source_anchors = EXCLUDED.source_anchors, updated_at = now()
"""

RESTORE_EDGES = """
INSERT INTO atlas_edges (id, graph_id, from_node_id, to_node_id, label, description,
    cardinality_from, cardinality_to, is_directed, properties, source, confidence,
    valid_from, valid_to, recorded_at, source_anchors, created_at, updated_at)
SELECT s.row_id, :g, (s.payload->>'from_node_id')::uuid, (s.payload->>'to_node_id')::uuid,
    coalesce(s.payload->>'label', 'related_to'), coalesce(s.payload->>'description', ''),
    s.payload->>'cardinality_from', s.payload->>'cardinality_to',
    coalesce((s.payload->>'is_directed')::boolean, true),
    coalesce(s.payload->'properties', '{}'::jsonb),
    coalesce(s.payload->>'source', 'user'), (s.payload->>'confidence')::float,
    (s.payload->>'valid_from')::timestamptz, (s.payload->>'valid_to')::timestamptz,
    coalesce((s.payload->>'recorded_at')::timestamptz, now()),
    NULLIF(s.payload->'source_anchors', 'null'::jsonb),
    coalesce((s.payload->>'created_at')::timestamptz, now()), now()
FROM atlas_restore_state s
WHERE s.kind = 'e' AND NOT s.deleted
  AND NOT EXISTS (SELECT 1 FROM atlas_edges l
                  WHERE l.id = s.row_id AND l.updated_at < :since)
  AND EXISTS (SELECT 1 FROM atlas_nodes n WHERE n.id = (s.payload->>'from_node_id')::uuid)
  AND EXISTS (SELECT 1 FROM atlas_nodes n WHERE n.id = (s.payload->>'to_node_id')::uuid)
ON CONFLICT (id) DO UPDATE SET
    from_node_id = EXCLUDED.from_node_id, to_node_id = EXCLUDED.to_node_id,
    label = EXCLUDED.label, description = EXCLUDED.description,
    cardinality_from = EXCLUDED.cardinality_from, cardinality_to = EXCLUDED.cardinality_to,
    is_directed = EXCLUDED.is_directed, properties = EXCLUDED.properties,
    source = EXCLUDED.source, confidence = EXCLUDED.confidence,
    valid_from = EXCLUDED.valid_from, valid_to = EXCLUDED.valid_to,
    source_anchors = EXCLUDED.source_anchors, updated_at = now()
"""


async def restore(db: AsyncSession, graph: AtlasGraph, snapshot: AtlasSnapshot) -> None:
    """Put the live rows back as they were, in SQL, keeping their ids."""
    params = {"g": graph.id, "v": snapshot.version}
    await db.execute(
        text(f"CREATE TEMP TABLE atlas_restore_state ON COMMIT DROP AS {LATEST_STATE}"),
        params,
    )
    await db.execute(
        text("CREATE INDEX ON atlas_restore_state (kind, row_id)"),
    )
    await db.execute(
        text(
            """
            DELETE FROM atlas_edges e WHERE e.graph_id = :g AND NOT EXISTS (
                SELECT 1 FROM atlas_restore_state s
                WHERE s.kind = 'e' AND s.row_id = e.id AND NOT s.deleted)
            """
        ),
        {"g": graph.id},
    )
    await db.execute(
        text(
            """
            DELETE FROM atlas_nodes n WHERE n.graph_id = :g AND NOT EXISTS (
                SELECT 1 FROM atlas_restore_state s
                WHERE s.kind = 'n' AND s.row_id = n.id AND NOT s.deleted)
            """
        ),
        {"g": graph.id},
    )
    # a row not touched since that snapshot already holds the right values
    since = snapshot.created_at - OVERLAP
    await db.execute(text(RESTORE_NODES), {"g": graph.id, "since": since})
    await db.execute(text(RESTORE_EDGES), {"g": graph.id, "since": since})
    await db.execute(
        text(
            """
            UPDATE atlas_edges e SET inverse_edge_id = (s.payload->>'inverse_edge_id')::uuid
            FROM atlas_restore_state s
            WHERE s.kind = 'e' AND s.row_id = e.id AND NOT s.deleted
              AND EXISTS (SELECT 1 FROM atlas_edges i
                          WHERE i.id = (s.payload->>'inverse_edge_id')::uuid)
            """
        )
    )
    await db.execute(text("DROP TABLE atlas_restore_state"))
