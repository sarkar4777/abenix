"""Atlas — unified ontology + knowledge-base canvas."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse
from sqlalchemy import desc, func, insert, or_, select, text, tuple_
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from app.core.deps import get_current_user, get_db
from app.core.permissions import is_admin, sees_other_users_resources
from app.core.responses import error, success

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))
from app.services import atlas_snapshots
from models.atlas import AtlasEdge, AtlasGraph, AtlasNode, AtlasNodeKind, AtlasSnapshot  # type: ignore
from models.knowledge_base import Document, KnowledgeBase  # type: ignore
from models.resource_share import ResourceShare, SharePermission  # type: ignore
from models.user import User  # type: ignore

# Reuses the BPM analyser's hardened multimodal pipeline.
from app.routers.bpm_analyzer import (  # type: ignore
    _build_anthropic_messages,
    default_vision_model,
    _parse_agent_specs,
    _process_upload,
    _provider_for,
    _run_vision_model,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/atlas", tags=["atlas"])

# past this the canvas works on a window of the graph and never loads it whole
FULL_GRAPH_LIMIT = 5000
WINDOW_LIMIT = 1000
READ_TIMEOUT_MS = 8000
SYNC_INLINE_DOCS = 500
SYNC_BATCH = 500
SUGGEST_FULL_NODES = 2000
QUERY_CANDIDATES = 200
QUERY_STEPS = 200_000


def _node_to_dict(n: AtlasNode) -> dict[str, Any]:
    return {
        "id": str(n.id),
        "graph_id": str(n.graph_id),
        "label": n.label,
        "kind": n.kind.value if hasattr(n.kind, "value") else str(n.kind),
        "description": n.description or "",
        "properties": n.properties or {},
        "position": (
            {"x": n.position_x, "y": n.position_y} if n.position_x is not None else None
        ),
        "document_id": str(n.document_id) if n.document_id else None,
        "source": n.source,
        "confidence": n.confidence,
        "tags": n.tags or [],
        "created_at": n.created_at.isoformat() if n.created_at else None,
        "updated_at": n.updated_at.isoformat() if n.updated_at else None,
    }


def _edge_to_dict(e: AtlasEdge) -> dict[str, Any]:
    return {
        "id": str(e.id),
        "graph_id": str(e.graph_id),
        "from_node_id": str(e.from_node_id),
        "to_node_id": str(e.to_node_id),
        "label": e.label,
        "description": e.description or "",
        "cardinality_from": e.cardinality_from,
        "cardinality_to": e.cardinality_to,
        "inverse_edge_id": str(e.inverse_edge_id) if e.inverse_edge_id else None,
        "is_directed": e.is_directed,
        "properties": e.properties or {},
        "source": e.source,
        "confidence": e.confidence,
    }


ATLAS_KIND = "atlas_graph"


def graph_ownership(g: Any, user: Any) -> str:
    if g.owner_user_id is None:
        return "platform"
    return "mine" if g.owner_user_id == user.id else "shared"


def can_view_graph(g: Any, user: Any, share: SharePermission | None = None) -> bool:
    """Owner, platform row, tenant-wide viewer, or any share."""
    if g.tenant_id != user.tenant_id:
        return False
    if g.owner_user_id is None or g.owner_user_id == user.id:
        return True
    return sees_other_users_resources(user) or share is not None


def can_edit_graph(g: Any, user: Any, share: SharePermission | None = None) -> bool:
    """Owner, tenant admin, or an EDIT share."""
    if g.tenant_id != user.tenant_id:
        return False
    if g.owner_user_id is not None and g.owner_user_id == user.id:
        return True
    return is_admin(user) or share == SharePermission.EDIT


def can_delete_graph(g: Any, user: Any) -> bool:
    if g.tenant_id != user.tenant_id:
        return False
    if g.owner_user_id is not None and g.owner_user_id == user.id:
        return True
    return is_admin(user)


def _annotate(
    g: AtlasGraph,
    user: User,
    share: SharePermission | None,
    owner_name: str | None,
) -> AtlasGraph:
    # Plain attribute, not a mapped column, so it never reaches the DB.
    g._access = {
        "owner_name": owner_name,
        "ownership": graph_ownership(g, user),
        "can_edit": can_edit_graph(g, user, share),
        "can_delete": can_delete_graph(g, user),
        "permission": share.value.lower() if share is not None else None,
    }
    return g


async def _owner_names(db: AsyncSession, ids: set[Any]) -> dict[uuid.UUID, str]:
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    rows = (
        await db.execute(
            select(User.id, User.full_name, User.email).where(User.id.in_(wanted))
        )
    ).all()
    return {r[0]: (r[1] or r[2]) for r in rows}


def _graph_meta(g: AtlasGraph) -> dict[str, Any]:
    access = getattr(g, "_access", None) or {}
    return {
        "id": str(g.id),
        "owner_id": str(g.owner_user_id) if g.owner_user_id else None,
        "owner_name": access.get("owner_name"),
        "ownership": access.get("ownership"),
        "can_edit": access.get("can_edit"),
        "can_delete": access.get("can_delete"),
        "permission": access.get("permission"),
        "name": g.name,
        "description": g.description or "",
        "kb_id": str(g.kb_id) if g.kb_id else None,
        "version": g.version,
        "node_count": g.node_count,
        "edge_count": g.edge_count,
        "settings": g.settings or {},
        "created_at": g.created_at.isoformat() if g.created_at else None,
        "updated_at": g.updated_at.isoformat() if g.updated_at else None,
    }


async def _share_for(
    db: AsyncSession, user: User, graph_id: uuid.UUID
) -> SharePermission | None:
    return (
        await db.execute(
            select(ResourceShare.permission).where(
                ResourceShare.resource_type == ATLAS_KIND,
                ResourceShare.resource_id == graph_id,
                ResourceShare.shared_with_user_id == user.id,
                ResourceShare.live(),
            )
        )
    ).scalar_one_or_none()


async def _load_graph(
    db: AsyncSession,
    graph_id: str,
    user: User,
    need: str = "view",
) -> AtlasGraph | JSONResponse:
    """Fetch a graph the caller may `need` (view, edit or delete)."""
    try:
        gid = uuid.UUID(graph_id)
    except ValueError:
        return error("Invalid graph id", 400)
    g = (
        await db.execute(select(AtlasGraph).where(AtlasGraph.id == gid))
    ).scalar_one_or_none()
    if not g or g.tenant_id != user.tenant_id:
        return error("Graph not found", 404)
    share = await _share_for(db, user, g.id)
    if not can_view_graph(g, user, share):
        return error("Graph not found", 404)
    if need == "edit" and not can_edit_graph(g, user, share):
        return error("Only the graph owner, an editor or an admin can change it", 403)
    if need == "delete" and not can_delete_graph(g, user):
        return error("Only the graph owner or an admin can delete this graph", 403)
    names = await _owner_names(db, {g.owner_user_id})
    return _annotate(g, user, share, names.get(g.owner_user_id))


async def _bump_version(
    db: AsyncSession,
    graph: AtlasGraph,
    nodes: int = 0,
    edges: int = 0,
    recount: bool = False,
) -> None:
    """Version and counts in one row update. Bulk writers ask for a recount."""
    await db.flush()
    node_expr = "node_count + :nodes"
    edge_expr = "edge_count + :edges"
    if recount:
        node_expr = "(SELECT count(*) FROM atlas_nodes WHERE graph_id = :g)"
        edge_expr = "(SELECT count(*) FROM atlas_edges WHERE graph_id = :g)"
    row = (
        await db.execute(
            text(
                f"""
                UPDATE atlas_graphs SET version = version + 1,
                    node_count = GREATEST({node_expr}, 0),
                    edge_count = GREATEST({edge_expr}, 0),
                    updated_at = now()
                WHERE id = :g
                RETURNING version, node_count, edge_count, updated_at
                """
            ),
            (
                {"g": graph.id}
                if recount
                else {"g": graph.id, "nodes": nodes, "edges": edges}
            ),
        )
    ).one()
    set_committed_value(graph, "version", row[0])
    set_committed_value(graph, "node_count", row[1])
    set_committed_value(graph, "edge_count", row[2])
    set_committed_value(graph, "updated_at", row[3])


async def _maybe_snapshot(
    db: AsyncSession,
    graph: AtlasGraph,
    user_id: uuid.UUID,
    *,
    label: str | None = None,
) -> None:
    """Snapshot the graph, rate-limited to one per 60s per graph."""
    await atlas_snapshots.maybe_capture(
        db, graph, user_id, label=label, meta=_graph_meta(graph)
    )


async def _read_guard(db: AsyncSession) -> None:
    """A browse query that cannot use its index gives up instead of tying up the pool."""
    await db.execute(
        text("SELECT set_config('statement_timeout', :ms, true)"),
        {"ms": str(READ_TIMEOUT_MS)},
    )


def _too_slow() -> JSONResponse:
    return error(
        "That query took too long on a graph this size. Narrow it with a search term or a kind.",
        422,
    )


@router.get("/graphs")
async def list_graphs(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = 100,
) -> JSONResponse:
    """Own, shared and platform graphs, or the whole tenant for admins."""
    share_rows = (
        await db.execute(
            select(ResourceShare.resource_id, ResourceShare.permission).where(
                ResourceShare.resource_type == ATLAS_KIND,
                ResourceShare.shared_with_user_id == user.id,
                ResourceShare.live(),
            )
        )
    ).all()
    shares = {r[0]: r[1] for r in share_rows}
    q = select(AtlasGraph).where(AtlasGraph.tenant_id == user.tenant_id)
    if not sees_other_users_resources(user):
        visible = [
            AtlasGraph.owner_user_id == user.id,
            AtlasGraph.owner_user_id.is_(None),
        ]
        if shares:
            visible.append(AtlasGraph.id.in_(list(shares)))
        q = q.where(or_(*visible))
    rows = (
        (
            await db.execute(
                q.order_by(desc(AtlasGraph.updated_at)).limit(min(max(limit, 1), 200))
            )
        )
        .scalars()
        .all()
    )
    names = await _owner_names(db, {g.owner_user_id for g in rows})
    for g in rows:
        _annotate(g, user, shares.get(g.id), names.get(g.owner_user_id))
    return success({"graphs": [_graph_meta(g) for g in rows]})


@router.post("/graphs")
async def create_graph(
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Create a new graph. Body: {name, description?, kb_id?}."""
    name = (body.get("name") or "Untitled Atlas").strip()[:255] or "Untitled Atlas"
    desc_text = (body.get("description") or "")[:5000]
    kb_id_raw = body.get("kb_id")
    kb_id: uuid.UUID | None = None
    if kb_id_raw:
        try:
            kb_id = uuid.UUID(kb_id_raw)
        except ValueError:
            return error("Invalid kb_id", 400)
        if not await _load_kb(db, kb_id, user):
            return error("Knowledge base not found", 404)
    g = AtlasGraph(
        id=uuid.uuid4(),
        tenant_id=user.tenant_id,
        owner_user_id=user.id,
        kb_id=kb_id,
        name=name,
        description=desc_text,
    )
    db.add(g)
    await db.commit()
    await db.refresh(g)
    _annotate(g, user, None, user.full_name or user.email)
    return success({"graph": _graph_meta(g)})


@router.get("/graphs/{graph_id}")
async def get_graph(
    graph_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    node_limit: int = FULL_GRAPH_LIMIT,
    after: str | None = None,
) -> JSONResponse:
    """Graph meta plus one page of nodes and the edges among them."""
    g = await _load_graph(db, graph_id, user)
    if isinstance(g, JSONResponse):
        return g
    limit = max(0, min(node_limit, FULL_GRAPH_LIMIT))
    if limit == 0:
        return success(
            {
                "graph": _graph_meta(g),
                "nodes": [],
                "edges": [],
                "truncated": (g.node_count or 0) > 0,
                "next_cursor": None,
                "limit": 0,
            }
        )
    q = select(AtlasNode).where(AtlasNode.graph_id == g.id)
    if after:
        try:
            stamp, last_id = after.split("|", 1)
            q = q.where(
                tuple_(AtlasNode.created_at, AtlasNode.id)
                > (datetime.fromisoformat(stamp), uuid.UUID(last_id))
            )
        except ValueError:
            return error("Invalid cursor", 400)
    rows = (
        (
            await db.execute(
                q.order_by(AtlasNode.created_at, AtlasNode.id).limit(limit + 1)
            )
        )
        .scalars()
        .all()
    )
    more = len(rows) > limit
    nodes = rows[:limit]
    edges = await _edges_among(db, g.id, [n.id for n in nodes], limit * 5)
    return success(
        {
            "graph": _graph_meta(g),
            "nodes": [_node_to_dict(n) for n in nodes],
            "edges": [_edge_to_dict(e) for e in edges],
            "truncated": more,
            "next_cursor": (
                f"{nodes[-1].created_at.isoformat()}|{nodes[-1].id}" if more else None
            ),
            "limit": limit,
        }
    )


async def _edges_among(
    db: AsyncSession, graph_id: uuid.UUID, ids: list[uuid.UUID], limit: int
) -> list[AtlasEdge]:
    if not ids:
        return []
    return list(
        (
            await db.execute(
                select(AtlasEdge)
                .where(
                    AtlasEdge.graph_id == graph_id,
                    AtlasEdge.from_node_id.in_(ids),
                    AtlasEdge.to_node_id.in_(ids),
                )
                .order_by(AtlasEdge.created_at)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )


def _window_limit(raw: int, default: int = 300) -> int:
    return max(1, min(raw or default, WINDOW_LIMIT))


def _window_payload(
    g: AtlasGraph, nodes: list[AtlasNode], edges: list[AtlasEdge], **extra: Any
) -> dict[str, Any]:
    return {
        "graph": _graph_meta(g),
        "nodes": [_node_to_dict(n) for n in nodes],
        "edges": [_edge_to_dict(e) for e in edges],
        **extra,
    }


@router.get("/graphs/{graph_id}/overview")
async def graph_overview(
    graph_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = 200,
) -> JSONResponse:
    """The most connected nodes, the place to start on a graph too big to draw."""
    g = await _load_graph(db, graph_id, user)
    if isinstance(g, JSONResponse):
        return g
    limit = _window_limit(limit, 200)
    try:
        await _read_guard(db)
        hubs = (
            await db.execute(
                text(
                    """
                    SELECT id FROM (
                        SELECT from_node_id AS id FROM atlas_edges WHERE graph_id = :g
                        UNION ALL
                        SELECT to_node_id FROM atlas_edges WHERE graph_id = :g
                    ) ends GROUP BY id ORDER BY count(*) DESC LIMIT :n
                    """
                ),
                {"g": g.id, "n": limit},
            )
        ).all()
        ids = [r[0] for r in hubs]
        nodes: list[AtlasNode] = []
        if ids:
            nodes = list(
                (await db.execute(select(AtlasNode).where(AtlasNode.id.in_(ids))))
                .scalars()
                .all()
            )
        if len(nodes) < limit:
            have = {n.id for n in nodes}
            extra = (
                (
                    await db.execute(
                        select(AtlasNode)
                        .where(AtlasNode.graph_id == g.id)
                        .order_by(AtlasNode.created_at, AtlasNode.id)
                        .limit(limit)
                    )
                )
                .scalars()
                .all()
            )
            nodes += [n for n in extra if n.id not in have][: limit - len(nodes)]
        edges = await _edges_among(db, g.id, [n.id for n in nodes], limit * 5)
    except DBAPIError as e:
        await db.rollback()
        logger.warning("atlas overview failed: %s", e)
        return _too_slow()
    return success(
        _window_payload(
            g,
            nodes,
            edges,
            limit=limit,
            center=str(ids[0]) if ids else None,
            truncated=(g.node_count or 0) > len(nodes),
        )
    )


@router.get("/graphs/{graph_id}/viewport")
async def graph_viewport(
    graph_id: str,
    min_x: float,
    min_y: float,
    max_x: float,
    max_y: float,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = 300,
    kind: str | None = None,
) -> JSONResponse:
    """Nodes inside a canvas rectangle, an even sample when more than the limit are there."""
    g = await _load_graph(db, graph_id, user)
    if isinstance(g, JSONResponse):
        return g
    limit = _window_limit(limit)
    conditions = [
        AtlasNode.graph_id == g.id,
        AtlasNode.position_x.between(min_x, max_x),
        AtlasNode.position_y.between(min_y, max_y),
    ]
    if kind:
        try:
            conditions.append(AtlasNode.kind == AtlasNodeKind(kind))
        except ValueError:
            return error(f"Invalid node kind {kind}", 400)
    try:
        await _read_guard(db)
        inside = (
            await db.execute(
                select(func.count()).select_from(
                    select(AtlasNode.id).where(*conditions).limit(10_001).subquery()
                )
            )
        ).scalar() or 0
        # ids are random, so sorting by them is a stable sample while panning
        nodes = list(
            (
                await db.execute(
                    select(AtlasNode)
                    .where(*conditions)
                    .order_by(AtlasNode.id)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        edges = await _edges_among(db, g.id, [n.id for n in nodes], limit * 5)
    except DBAPIError as e:
        await db.rollback()
        logger.warning("atlas viewport failed: %s", e)
        return _too_slow()
    return success(
        _window_payload(
            g,
            nodes,
            edges,
            limit=limit,
            in_view=inside,
            in_view_capped=inside > 10_000,
            truncated=inside > len(nodes),
        )
    )


@router.get("/graphs/{graph_id}/neighbourhood")
async def graph_neighbourhood(
    graph_id: str,
    node_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    hops: int = 1,
    limit: int = 100,
    fanout: int = 50,
) -> JSONResponse:
    """A node and what it connects to, a set number of edges per node so hubs stay usable."""
    g = await _load_graph(db, graph_id, user)
    if isinstance(g, JSONResponse):
        return g
    try:
        start = uuid.UUID(node_id)
    except ValueError:
        return error("Invalid node id", 400)
    limit = _window_limit(limit, 100)
    hops = max(1, min(hops, 3))
    fanout = max(1, min(fanout, 200))
    try:
        await _read_guard(db)
        origin = (
            await db.execute(
                select(AtlasNode).where(
                    AtlasNode.id == start, AtlasNode.graph_id == g.id
                )
            )
        ).scalar_one_or_none()
        if origin is None:
            return error("Node not found", 404)
        seen: dict[uuid.UUID, int] = {start: 0}
        edge_ids: list[uuid.UUID] = []
        frontier = [start]
        truncated = False
        for hop in range(1, hops + 1):
            rows = (
                await db.execute(
                    text(
                        """
                        SELECT e.id, e.from_node_id, e.to_node_id
                        FROM unnest(CAST(:frontier AS uuid[])) AS f(id)
                        CROSS JOIN LATERAL (
                            (SELECT x.id, x.from_node_id, x.to_node_id FROM atlas_edges x
                             WHERE x.from_node_id = f.id AND x.graph_id = :g LIMIT :fan)
                            UNION ALL
                            (SELECT x.id, x.from_node_id, x.to_node_id FROM atlas_edges x
                             WHERE x.to_node_id = f.id AND x.graph_id = :g LIMIT :fan)
                        ) e
                        """
                    ),
                    {"frontier": frontier, "g": g.id, "fan": fanout},
                )
            ).all()
            if len(rows) >= fanout * len(frontier):
                truncated = True
            next_frontier: list[uuid.UUID] = []
            for eid, a, b in rows:
                for other in (a, b):
                    if other not in seen:
                        if len(seen) >= limit:
                            truncated = True
                            continue
                        seen[other] = hop
                        next_frontier.append(other)
                if a in seen and b in seen:
                    edge_ids.append(eid)
            frontier = next_frontier
            if not frontier:
                break
        nodes = list(
            (await db.execute(select(AtlasNode).where(AtlasNode.id.in_(list(seen)))))
            .scalars()
            .all()
        )
        edges = list(
            (
                await db.execute(
                    select(AtlasEdge).where(AtlasEdge.id.in_(list(set(edge_ids))))
                )
            )
            .scalars()
            .all()
        )
        degree = (
            await db.execute(
                text(
                    """
                    SELECT count(*) FROM (
                        SELECT 1 FROM atlas_edges WHERE from_node_id = :n
                        UNION ALL SELECT 1 FROM atlas_edges WHERE to_node_id = :n
                        LIMIT 10001) d
                    """
                ),
                {"n": start},
            )
        ).scalar()
    except DBAPIError as e:
        await db.rollback()
        logger.warning("atlas neighbourhood failed: %s", e)
        return _too_slow()
    return success(
        _window_payload(
            g,
            nodes,
            edges,
            center=str(start),
            hops=hops,
            limit=limit,
            degree=degree,
            truncated=truncated,
        )
    )


@router.get("/graphs/{graph_id}/search")
async def search_nodes(
    graph_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    q: str = "",
    kind: str | None = None,
    limit: int = 50,
    after: str | None = None,
) -> JSONResponse:
    """Nodes whose label contains the text, keyset paged by label."""
    g = await _load_graph(db, graph_id, user)
    if isinstance(g, JSONResponse):
        return g
    limit = max(1, min(limit, 200))
    term = q.strip().lower()
    conditions = [AtlasNode.graph_id == g.id]
    if term:
        escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        conditions.append(func.lower(AtlasNode.label).like(f"%{escaped}%", escape="\\"))
    if kind:
        try:
            conditions.append(AtlasNode.kind == AtlasNodeKind(kind))
        except ValueError:
            return error(f"Invalid node kind {kind}", 400)
    if after:
        try:
            label, last = after.rsplit("|", 1)
            conditions.append(
                tuple_(AtlasNode.label, AtlasNode.id) > (label, uuid.UUID(last))
            )
        except ValueError:
            return error("Invalid cursor", 400)
    try:
        await _read_guard(db)
        rows = (
            (
                await db.execute(
                    select(AtlasNode)
                    .where(*conditions)
                    .order_by(AtlasNode.label, AtlasNode.id)
                    .limit(limit + 1)
                )
            )
            .scalars()
            .all()
        )
    except DBAPIError as e:
        await db.rollback()
        logger.warning("atlas search failed: %s", e)
        return _too_slow()
    more = len(rows) > limit
    rows = rows[:limit]
    return success(
        {
            "nodes": [_node_to_dict(n) for n in rows],
            "next_cursor": f"{rows[-1].label}|{rows[-1].id}" if more else None,
            "limit": limit,
        }
    )


@router.patch("/graphs/{graph_id}")
async def patch_graph(
    graph_id: str,
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    g = await _load_graph(db, graph_id, user, need="edit")
    if isinstance(g, JSONResponse):
        return g
    if "name" in body:
        g.name = (body["name"] or "Untitled Atlas").strip()[:255] or "Untitled Atlas"
    if "description" in body:
        g.description = (body.get("description") or "")[:5000]
    if "settings" in body and isinstance(body["settings"], dict):
        g.settings = {**(g.settings or {}), **body["settings"]}
    await _bump_version(db, g)
    await db.commit()
    await db.refresh(g)
    return success({"graph": _graph_meta(g)})


@router.delete("/graphs/{graph_id}")
async def delete_graph(
    graph_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    g = await _load_graph(db, graph_id, user, need="delete")
    if isinstance(g, JSONResponse):
        return g
    await db.delete(g)
    await db.commit()
    return success({"deleted": True})


@router.post("/graphs/{graph_id}/nodes")
async def create_node(
    graph_id: str,
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    g = await _load_graph(db, graph_id, user, need="edit")
    if isinstance(g, JSONResponse):
        return g
    label = (body.get("label") or "").strip()[:255]
    if not label:
        return error("label is required", 400)
    kind_raw = (body.get("kind") or "concept").lower()
    try:
        kind = AtlasNodeKind(kind_raw)
    except ValueError:
        return error(f"Invalid node kind {kind_raw}", 400)
    pos = body.get("position") or {}
    n = AtlasNode(
        id=uuid.uuid4(),
        graph_id=g.id,
        label=label,
        kind=kind,
        description=(body.get("description") or "")[:5000],
        properties=body.get("properties") or {},
        position_x=pos.get("x"),
        position_y=pos.get("y"),
        source=(body.get("source") or "user")[:40],
        confidence=body.get("confidence"),
        tags=body.get("tags") or [],
    )
    db.add(n)
    await _bump_version(db, g, nodes=1)
    await _maybe_snapshot(db, g, user.id)
    await db.commit()
    await db.refresh(n)
    await db.refresh(g)
    return success({"node": _node_to_dict(n), "graph": _graph_meta(g)})


@router.patch("/graphs/{graph_id}/nodes/{node_id}")
async def patch_node(
    graph_id: str,
    node_id: str,
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    g = await _load_graph(db, graph_id, user, need="edit")
    if isinstance(g, JSONResponse):
        return g
    try:
        nid = uuid.UUID(node_id)
    except ValueError:
        return error("Invalid node id", 400)
    n = (
        await db.execute(
            select(AtlasNode).where(AtlasNode.id == nid, AtlasNode.graph_id == g.id)
        )
    ).scalar_one_or_none()
    if not n:
        return error("Node not found", 404)
    if "label" in body:
        n.label = (body["label"] or "").strip()[:255] or n.label
    if "description" in body:
        n.description = (body.get("description") or "")[:5000]
    if "kind" in body:
        try:
            n.kind = AtlasNodeKind(body["kind"])
        except ValueError:
            return error(f"Invalid node kind {body['kind']}", 400)
    if "properties" in body and isinstance(body["properties"], dict):
        n.properties = body["properties"]
    if "position" in body and isinstance(body["position"], dict):
        n.position_x = body["position"].get("x")
        n.position_y = body["position"].get("y")
    if "tags" in body and isinstance(body["tags"], list):
        n.tags = body["tags"]
    if "source" in body:
        n.source = body["source"][:40]
    n.updated_at = datetime.now(timezone.utc)
    await _bump_version(db, g)
    await db.commit()
    await db.refresh(n)
    return success({"node": _node_to_dict(n)})


@router.delete("/graphs/{graph_id}/nodes/{node_id}")
async def delete_node(
    graph_id: str,
    node_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    g = await _load_graph(db, graph_id, user, need="edit")
    if isinstance(g, JSONResponse):
        return g
    try:
        nid = uuid.UUID(node_id)
    except ValueError:
        return error("Invalid node id", 400)
    n = (
        await db.execute(
            select(AtlasNode).where(AtlasNode.id == nid, AtlasNode.graph_id == g.id)
        )
    ).scalar_one_or_none()
    if not n:
        return error("Node not found", 404)
    cascaded = (
        await db.execute(
            select(func.count())
            .select_from(AtlasEdge)
            .where(or_(AtlasEdge.from_node_id == nid, AtlasEdge.to_node_id == nid))
        )
    ).scalar() or 0
    await db.delete(n)
    await _bump_version(db, g, nodes=-1, edges=-cascaded)
    await _maybe_snapshot(db, g, user.id)
    await db.commit()
    return success({"deleted": True})


@router.post("/graphs/{graph_id}/edges")
async def create_edge(
    graph_id: str,
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    g = await _load_graph(db, graph_id, user, need="edit")
    if isinstance(g, JSONResponse):
        return g
    try:
        from_id = uuid.UUID(body.get("from_node_id"))
        to_id = uuid.UUID(body.get("to_node_id"))
    except (TypeError, ValueError):
        return error("from_node_id and to_node_id must be UUIDs", 400)
    nodes = (
        (
            await db.execute(
                select(AtlasNode).where(
                    AtlasNode.graph_id == g.id, AtlasNode.id.in_([from_id, to_id])
                )
            )
        )
        .scalars()
        .all()
    )
    if len(nodes) != len({from_id, to_id}):
        return error("Both endpoints must exist in this graph", 400)
    e = AtlasEdge(
        id=uuid.uuid4(),
        graph_id=g.id,
        from_node_id=from_id,
        to_node_id=to_id,
        label=(body.get("label") or "related_to").strip()[:255] or "related_to",
        description=(body.get("description") or "")[:5000],
        cardinality_from=(body.get("cardinality_from") or None),
        cardinality_to=(body.get("cardinality_to") or None),
        is_directed=bool(body.get("is_directed", True)),
        properties=body.get("properties") or {},
        source=(body.get("source") or "user")[:40],
        confidence=body.get("confidence"),
    )
    db.add(e)
    await _bump_version(db, g, edges=1)
    await db.commit()
    await db.refresh(e)
    await db.refresh(g)
    return success({"edge": _edge_to_dict(e), "graph": _graph_meta(g)})


@router.patch("/graphs/{graph_id}/edges/{edge_id}")
async def patch_edge(
    graph_id: str,
    edge_id: str,
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    g = await _load_graph(db, graph_id, user, need="edit")
    if isinstance(g, JSONResponse):
        return g
    try:
        eid = uuid.UUID(edge_id)
    except ValueError:
        return error("Invalid edge id", 400)
    e = (
        await db.execute(
            select(AtlasEdge).where(AtlasEdge.id == eid, AtlasEdge.graph_id == g.id)
        )
    ).scalar_one_or_none()
    if not e:
        return error("Edge not found", 404)
    if "label" in body:
        e.label = (body["label"] or "related_to").strip()[:255] or e.label
    if "description" in body:
        e.description = (body["description"] or "")[:5000]
    if "cardinality_from" in body:
        e.cardinality_from = body["cardinality_from"]
    if "cardinality_to" in body:
        e.cardinality_to = body["cardinality_to"]
    if "is_directed" in body:
        e.is_directed = bool(body["is_directed"])
    if "properties" in body and isinstance(body["properties"], dict):
        e.properties = body["properties"]
    if "inverse_edge_id" in body:
        if body["inverse_edge_id"] is None:
            e.inverse_edge_id = None
        else:
            try:
                e.inverse_edge_id = uuid.UUID(body["inverse_edge_id"])
            except ValueError:
                return error("Invalid inverse_edge_id", 400)
    e.updated_at = datetime.now(timezone.utc)
    await _bump_version(db, g)
    await db.commit()
    await db.refresh(e)
    return success({"edge": _edge_to_dict(e)})


@router.delete("/graphs/{graph_id}/edges/{edge_id}")
async def delete_edge(
    graph_id: str,
    edge_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    g = await _load_graph(db, graph_id, user, need="edit")
    if isinstance(g, JSONResponse):
        return g
    try:
        eid = uuid.UUID(edge_id)
    except ValueError:
        return error("Invalid edge id", 400)
    e = (
        await db.execute(
            select(AtlasEdge).where(AtlasEdge.id == eid, AtlasEdge.graph_id == g.id)
        )
    ).scalar_one_or_none()
    if not e:
        return error("Edge not found", 404)
    await db.delete(e)
    await _bump_version(db, g, edges=-1)
    await db.commit()
    return success({"deleted": True})


_NL_SYSTEM_PROMPT = (
    "You are Atlas — an ontology editor. The user types natural-language "
    "sentences about a domain; you turn each sentence into a structured "
    "list of graph operations.\n\n"
    "Supported operations (always emit a JSON object with exactly an "
    "`agents` field which is an array of these — the field name is "
    "fixed for parser compatibility, but each item is an op record):\n"
    '  { "op": "add_node", "label": "<concept>", '
    '"kind": "concept|instance|document|property", '
    '"description": "<optional>", "tags": ["<optional>"] }\n'
    '  { "op": "add_edge", "from": "<source label>", "to": "<target label>", '
    '"label": "<verb>", "cardinality_from": "1|0..1|*|1..*", '
    '"cardinality_to": "1|0..1|*|1..*", "description": "<optional>" }\n\n'
    "Rules:\n"
    "  * If a concept is referenced but not yet defined, emit an "
    "`add_node` for it before the `add_edge`.\n"
    "  * Infer cardinality from natural words: `has many`, `each`, "
    "`exactly one`, `optional`, `multiple`.\n"
    "  * Default verb when none given: `related_to`.\n"
    '  * For "X has Y" with no quantifier, default cardinality_from=1, '
    "cardinality_to=*.\n"
    "  * Use Title Case for concept labels, snake_case for edge labels.\n\n"
    "Reply with PURE JSON only. First character `{`, last character `}`."
)


@router.post("/graphs/{graph_id}/parse-nl")
async def parse_nl(
    graph_id: str,
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Parse a natural-language sentence into a list of graph ops."""
    g = await _load_graph(db, graph_id, user, need="edit")
    if isinstance(g, JSONResponse):
        return g
    text = (body.get("text") or "").strip()
    if not text:
        return error("text is required", 400)
    model = (body.get("model") or default_vision_model()).strip()

    # Reuse the BPM analyser's message builder + dispatcher. We pass an
    # empty attachments list — this is text-only — and the user's
    # sentence as the question.
    msgs = _build_anthropic_messages([], history_turns=[], new_user_question=text)
    try:
        reply, meta = await _run_vision_model(
            system_prompt=_NL_SYSTEM_PROMPT,
            messages=msgs,
            model=model,
            force_json=True,
        )
    except Exception as e:
        logger.exception("Atlas parse-nl call failed")
        return error(f"Parse failed: {e}", 502)
    parsed = _parse_agent_specs(reply)
    if not parsed or not isinstance(parsed.get("agents"), list):
        return error(
            "Could not parse the sentence into operations — try "
            "a different phrasing or a stronger model",
            502,
        )
    return success(
        {
            "ops": parsed["agents"],
            "model": meta.get("model") or model,
            "cost": meta.get("cost", 0.0),
            "duration_ms": meta.get("duration_ms", 0),
        }
    )


_EXTRACT_SYSTEM_PROMPT = (
    "You are Atlas Extractor. The user has uploaded a document, image, "
    "audio recording, video, or text. Your job is to read it and "
    "propose an ontology fragment — concepts, relationships, key "
    "properties — that captures the domain it describes.\n\n"
    "Reply with PURE JSON only, in this exact shape (the field name "
    "`agents` is required for parser compatibility, but each entry is "
    "an op):\n"
    '  {"agents": [\n'
    '    {"op": "add_node", "label": "<TitleCase concept>", '
    '"kind": "concept", "description": "<one line>", '
    '"properties": {<typed attributes>}, "confidence": 0.0..1.0},\n'
    '    {"op": "add_edge", "from": "<source label>", "to": '
    '"<target label>", "label": "<snake_case verb>", '
    '"cardinality_from": "1|0..1|*|1..*", '
    '"cardinality_to": "1|0..1|*|1..*", "confidence": 0.0..1.0}\n'
    "  ]}\n\n"
    "Rules:\n"
    "  * Only include things the artefact actually mentions or implies.\n"
    "  * Confidence reflects how directly the artefact stated it.\n"
    "  * Don't invent properties; pull them straight from the source.\n"
    "  * No prose, no fences, no comments. First char `{`, last `}`."
)


@router.post("/graphs/{graph_id}/extract")
async def extract_from_upload(
    graph_id: str,
    request: Request,
    file: UploadFile | None = File(None),
    text: str = Form(""),
    model: str = Form(""),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Drop a doc/image/audio/video/text → proposed nodes + edges."""
    g = await _load_graph(db, graph_id, user, need="edit")
    if isinstance(g, JSONResponse):
        return g

    attachments: list[dict[str, Any]] = []
    required_provider = ""
    if file is not None and file.filename:
        raw = await file.read()
        if not raw:
            return error("Empty file", 400)
        if len(raw) > 50 * 1024 * 1024:
            return error("Upload exceeds 50 MB limit", 413)
        try:
            attachments, required_provider = _process_upload(
                raw,
                file.content_type or "",
                file.filename or "",
            )
        except Exception as e:
            logger.exception("Atlas extract upload processing failed")
            return error(f"Could not process upload: {e}", 415)
    elif text.strip():
        attachments = [
            {
                "type": "text_doc",
                "text": text[:200000],
                "filename": "user-input.txt",
                "doc_kind": "txt",
            }
        ]
    else:
        return error("Provide either a file or text", 400)

    chosen_model = (model or "").strip() or default_vision_model()
    if required_provider and _provider_for(chosen_model) != required_provider:
        chosen_model = default_vision_model()

    seed = "Read the attached artefact and propose an ontology fragment."
    msgs = _build_anthropic_messages(
        attachments,
        history_turns=[],
        new_user_question=seed,
    )
    try:
        reply, meta = await _run_vision_model(
            system_prompt=_EXTRACT_SYSTEM_PROMPT,
            messages=msgs,
            model=chosen_model,
            force_json=True,
        )
    except Exception as e:
        logger.exception("Atlas extract LLM call failed")
        return error(f"Extraction failed: {e}", 502)
    parsed = _parse_agent_specs(reply)
    if not parsed or not isinstance(parsed.get("agents"), list):
        return error(
            "Extractor could not produce parseable proposals — "
            "try a different model or simplify the source",
            502,
        )

    return success(
        {
            "ops": parsed["agents"],
            "model": meta.get("model") or chosen_model,
            "cost": meta.get("cost", 0.0),
            "duration_ms": meta.get("duration_ms", 0),
            "primary_type": attachments[0].get("type") if attachments else None,
        }
    )


@router.post("/graphs/{graph_id}/apply")
async def apply_ops(
    graph_id: str,
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Apply a list of ops returned from parse-nl or extract."""
    g = await _load_graph(db, graph_id, user, need="edit")
    if isinstance(g, JSONResponse):
        return g

    ops = body.get("ops") or []
    if not isinstance(ops, list):
        return error("ops must be an array", 400)
    auto_layout = bool(body.get("auto_layout", True))

    # Only the labels these ops mention, the extractor often names what the user drew
    mentioned: set[str] = set()
    for op in ops:
        if isinstance(op, dict):
            for key in ("label", "from", "to"):
                value = op.get(key)
                if isinstance(value, str) and value.strip():
                    mentioned.add(value.strip()[:255].lower())
    existing_nodes = (
        (
            await db.execute(
                select(AtlasNode).where(
                    AtlasNode.graph_id == g.id,
                    func.lower(AtlasNode.label).in_(mentioned),
                )
            )
        )
        .scalars()
        .all()
        if mentioned
        else []
    )
    by_label: dict[str, AtlasNode] = {n.label.lower(): n for n in existing_nodes}

    created_nodes: list[AtlasNode] = []
    created_edges: list[AtlasEdge] = []
    skipped: int = 0

    # First pass — add_node ops. Ensures add_edge can find both ends.
    for op in ops:
        if not isinstance(op, dict):
            skipped += 1
            continue
        kind_raw = (op.get("op") or "").lower()
        if kind_raw != "add_node":
            continue
        label = (op.get("label") or "").strip()[:255]
        if not label:
            skipped += 1
            continue
        if label.lower() in by_label:
            continue
        try:
            node_kind = AtlasNodeKind(op.get("kind") or "concept")
        except ValueError:
            node_kind = AtlasNodeKind.CONCEPT
        n = AtlasNode(
            id=uuid.uuid4(),
            graph_id=g.id,
            label=label,
            kind=node_kind,
            description=(op.get("description") or "")[:5000],
            properties=op.get("properties") or {},
            source=(op.get("source") or "extractor")[:40],
            confidence=op.get("confidence"),
            tags=op.get("tags") or [],
        )
        db.add(n)
        by_label[label.lower()] = n
        created_nodes.append(n)
    await db.flush()

    # Auto-layout: arrange new nodes on a circle around the centroid
    # of existing positions, leaving the user's hand-positioned nodes
    # untouched. Cheap, deterministic, and looks intentional.
    if auto_layout and created_nodes:
        import math

        created_ids = [n.id for n in created_nodes]
        centre = (
            await db.execute(
                select(
                    func.avg(AtlasNode.position_x), func.avg(AtlasNode.position_y)
                ).where(
                    AtlasNode.graph_id == g.id,
                    AtlasNode.position_x.is_not(None),
                    AtlasNode.position_y.is_not(None),
                    AtlasNode.id.not_in(created_ids),
                )
            )
        ).one()
        if centre[0] is not None:
            cx, cy = float(centre[0]), float(centre[1])
        else:
            cx, cy = 400.0, 300.0
        radius = 240 + 18 * len(created_nodes)
        for i, n in enumerate(created_nodes):
            theta = (2 * math.pi * i) / max(len(created_nodes), 1)
            n.position_x = round(cx + radius * math.cos(theta), 1)
            n.position_y = round(cy + radius * math.sin(theta), 1)

    # Second pass — add_edge ops. Resolved against the merged label map.
    for op in ops:
        if not isinstance(op, dict):
            continue
        if (op.get("op") or "").lower() != "add_edge":
            continue
        src = (op.get("from") or "").strip().lower()
        dst = (op.get("to") or "").strip().lower()
        if not src or not dst:
            skipped += 1
            continue
        sn = by_label.get(src)
        dn = by_label.get(dst)
        if not sn or not dn:
            skipped += 1
            continue
        e = AtlasEdge(
            id=uuid.uuid4(),
            graph_id=g.id,
            from_node_id=sn.id,
            to_node_id=dn.id,
            label=(op.get("label") or "related_to").strip()[:255] or "related_to",
            description=(op.get("description") or "")[:5000],
            cardinality_from=op.get("cardinality_from"),
            cardinality_to=op.get("cardinality_to"),
            is_directed=bool(op.get("is_directed", True)),
            properties=op.get("properties") or {},
            source=(op.get("source") or "extractor")[:40],
            confidence=op.get("confidence"),
        )
        db.add(e)
        created_edges.append(e)

    await _bump_version(db, g, nodes=len(created_nodes), edges=len(created_edges))
    await _maybe_snapshot(db, g, user.id, label="ops apply")
    await db.commit()
    await db.refresh(g)
    return success(
        {
            "graph": _graph_meta(g),
            "created_nodes": [_node_to_dict(n) for n in created_nodes],
            "created_edges": [_edge_to_dict(e) for e in created_edges],
            "skipped": skipped,
        }
    )


def _suggestions_for_graph(
    nodes: list[AtlasNode],
    edges: list[AtlasEdge],
) -> list[dict[str, Any]]:
    """Heuristic-only suggestion engine."""
    out: list[dict[str, Any]] = []

    # 1. Possible duplicate nodes by case-insensitive prefix match
    {n.label.lower(): n for n in nodes}
    seen_pairs: set[tuple[str, str]] = set()
    for a in nodes:
        la = a.label.lower()
        for b in nodes:
            if a.id == b.id:
                continue
            lb = b.label.lower()
            if (lb, la) in seen_pairs:
                continue
            if (
                la
                and lb
                and (la in lb or lb in la)
                and abs(len(la) - len(lb)) <= 4
                and la != lb
            ):
                seen_pairs.add((la, lb))
                out.append(
                    {
                        "kind": "possible_duplicate",
                        "title": f"`{a.label}` and `{b.label}` look similar",
                        "detail": "Same prefix or substring — consider merging or "
                        "renaming one of them so the ontology stays terse.",
                        "node_ids": [str(a.id), str(b.id)],
                        "severity": "info",
                    }
                )
                if len(out) > 30:
                    return out

    # 2. Missing inverse edges
    {(str(e.from_node_id), str(e.to_node_id), e.label) for e in edges}
    for e in edges:
        # If there's no opposite-direction edge between the same nodes,
        # the inverse is missing. We don't auto-create — we suggest.
        if not any(
            ee.from_node_id == e.to_node_id and ee.to_node_id == e.from_node_id
            for ee in edges
        ):
            from_node = next((n for n in nodes if n.id == e.from_node_id), None)
            to_node = next((n for n in nodes if n.id == e.to_node_id), None)
            if from_node and to_node:
                out.append(
                    {
                        "kind": "missing_inverse",
                        "title": f"`{e.label}` has no inverse on `{to_node.label}`",
                        "detail": (
                            f"Add an edge from `{to_node.label}` to "
                            f"`{from_node.label}` so the graph is "
                            "navigable in both directions."
                        ),
                        "edge_id": str(e.id),
                        "from_node_id": str(e.from_node_id),
                        "to_node_id": str(e.to_node_id),
                        "severity": "info",
                    }
                )
                if len(out) > 30:
                    return out

    # 3. Concepts with zero edges (orphans)
    connected = {e.from_node_id for e in edges} | {e.to_node_id for e in edges}
    for n in nodes:
        if n.kind != AtlasNodeKind.CONCEPT:
            continue
        if n.id not in connected:
            out.append(
                {
                    "kind": "orphan_node",
                    "title": f"`{n.label}` is disconnected",
                    "detail": "No edges connect this concept. Either delete it "
                    "or relate it to something so it earns its place.",
                    "node_ids": [str(n.id)],
                    "severity": "warning",
                }
            )
            if len(out) > 30:
                break

    # 4. Edges that drop their cardinality on both sides
    missing_card = [e for e in edges if not e.cardinality_from and not e.cardinality_to]
    if len(missing_card) >= 3:
        out.append(
            {
                "kind": "missing_cardinalities",
                "title": f"{len(missing_card)} edges have no cardinality",
                "detail": "Add cardinalities (`1`, `0..1`, `*`, `1..*`) so "
                "constraint validation can run.",
                "edge_ids": [str(e.id) for e in missing_card[:20]],
                "severity": "info",
            }
        )

    return out


@router.get("/graphs/{graph_id}/suggestions")
async def suggestions(
    graph_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Ghost-cursor suggestions: duplicates, missing inverses, orphans."""
    g = await _load_graph(db, graph_id, user)
    if isinstance(g, JSONResponse):
        return g
    if (g.node_count or 0) > SUGGEST_FULL_NODES:
        return success(
            {"suggestions": await _suggestions_at_scale(db, g), "sampled": True}
        )
    nodes = (
        (await db.execute(select(AtlasNode).where(AtlasNode.graph_id == g.id)))
        .scalars()
        .all()
    )
    edges = (
        (await db.execute(select(AtlasEdge).where(AtlasEdge.graph_id == g.id)))
        .scalars()
        .all()
    )
    return success({"suggestions": _suggestions_for_graph(list(nodes), list(edges))})


async def _suggestions_at_scale(
    db: AsyncSession, g: AtlasGraph
) -> list[dict[str, Any]]:
    """The checks SQL can do on a big graph, exact duplicates and orphans, a few of each."""
    out: list[dict[str, Any]] = []
    try:
        await _read_guard(db)
        dupes = (
            await db.execute(
                text(
                    """
                    SELECT lower(label), array_agg(id) FROM atlas_nodes
                    WHERE graph_id = :g GROUP BY lower(label)
                    HAVING count(*) > 1 LIMIT 20
                    """
                ),
                {"g": g.id},
            )
        ).all()
        for label, ids in dupes:
            out.append(
                {
                    "kind": "possible_duplicate",
                    "title": f"{len(ids)} nodes are labelled `{label}`",
                    "detail": "Merge them if they mean the same thing.",
                    "severity": "warning",
                    "node_ids": [str(i) for i in ids[:10]],
                }
            )
        orphans = (
            await db.execute(
                text(
                    """
                    SELECT n.id, n.label FROM atlas_nodes n
                    WHERE n.graph_id = :g AND NOT EXISTS (
                        SELECT 1 FROM atlas_edges e
                        WHERE e.from_node_id = n.id OR e.to_node_id = n.id)
                    LIMIT 20
                    """
                ),
                {"g": g.id},
            )
        ).all()
        for node_id, label in orphans:
            out.append(
                {
                    "kind": "orphan_node",
                    "title": f"`{label}` has no relationships",
                    "detail": "Connect it or remove it.",
                    "severity": "info",
                    "node_ids": [str(node_id)],
                }
            )
    except DBAPIError as e:
        await db.rollback()
        logger.warning("atlas suggestions failed: %s", e)
    return out


@router.get("/graphs/{graph_id}/snapshots")
async def list_snapshots(
    graph_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = 100,
) -> JSONResponse:
    g = await _load_graph(db, graph_id, user)
    if isinstance(g, JSONResponse):
        return g
    rows = (
        (
            await db.execute(
                select(AtlasSnapshot)
                .where(AtlasSnapshot.graph_id == g.id)
                .order_by(desc(AtlasSnapshot.created_at))
                .limit(min(max(limit, 1), 500))
            )
        )
        .scalars()
        .all()
    )
    return success(
        {
            "snapshots": [
                {
                    "id": str(s.id),
                    "version": s.version,
                    "label": s.label,
                    "auto": s.auto,
                    "created_at": s.created_at.isoformat() if s.created_at else None,
                }
                for s in rows
            ],
        }
    )


@router.post("/graphs/{graph_id}/snapshots")
async def capture_snapshot(
    graph_id: str,
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Manual snapshot: not rate-limited, labelled by the user."""
    g = await _load_graph(db, graph_id, user, need="edit")
    if isinstance(g, JSONResponse):
        return g
    snap = await atlas_snapshots.capture(
        db,
        g,
        user.id,
        label=(body.get("label") or "manual checkpoint")[:255],
        auto=False,
        meta=_graph_meta(g),
    )
    snapshot_id, version = snap.id, snap.version
    await db.commit()
    return success({"id": str(snapshot_id), "version": version})


@router.post("/graphs/{graph_id}/snapshots/{snapshot_id}/restore")
async def restore_snapshot(
    graph_id: str,
    snapshot_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Replay a snapshot: wipe live nodes/edges, recreate from payload."""
    g = await _load_graph(db, graph_id, user, need="edit")
    if isinstance(g, JSONResponse):
        return g
    try:
        sid = uuid.UUID(snapshot_id)
    except ValueError:
        return error("Invalid snapshot id", 400)
    snap = (
        await db.execute(
            select(AtlasSnapshot).where(
                AtlasSnapshot.id == sid,
                AtlasSnapshot.graph_id == g.id,
            )
        )
    ).scalar_one_or_none()
    if not snap:
        return error("Snapshot not found", 404)

    # Save the current state first, the rate limit does not apply to a restore.
    await atlas_snapshots.capture(
        db, g, user.id, label="pre-restore", meta=_graph_meta(g)
    )

    if atlas_snapshots.is_diff(snap):
        await atlas_snapshots.restore(db, g, snap)
        await _bump_version(db, g, recount=True)
        version = g.version
        await db.commit()
        return success({"restored": True, "version": version})

    # Snapshots from before row versions hold the whole graph in their payload
    await db.execute(text("DELETE FROM atlas_edges WHERE graph_id = :g"), {"g": g.id})
    await db.execute(text("DELETE FROM atlas_nodes WHERE graph_id = :g"), {"g": g.id})

    payload = snap.payload or {}
    label_to_id: dict[str, uuid.UUID] = {}
    for n_dict in payload.get("nodes", []):
        nid = uuid.uuid4()
        kind_str = n_dict.get("kind", "concept")
        try:
            kind = AtlasNodeKind(kind_str)
        except ValueError:
            kind = AtlasNodeKind.CONCEPT
        pos = n_dict.get("position") or {}
        n = AtlasNode(
            id=nid,
            graph_id=g.id,
            label=n_dict.get("label", "Untitled")[:255],
            kind=kind,
            description=n_dict.get("description", "")[:5000],
            properties=n_dict.get("properties") or {},
            position_x=pos.get("x"),
            position_y=pos.get("y"),
            source=n_dict.get("source", "user")[:40],
            confidence=n_dict.get("confidence"),
            tags=n_dict.get("tags") or [],
        )
        db.add(n)
        # Map old-id -> new-id so edges can re-bind.
        if n_dict.get("id"):
            label_to_id[str(n_dict["id"])] = nid
    await db.flush()

    for e_dict in payload.get("edges", []):
        from_old = str(e_dict.get("from_node_id", ""))
        to_old = str(e_dict.get("to_node_id", ""))
        from_new = label_to_id.get(from_old)
        to_new = label_to_id.get(to_old)
        if not from_new or not to_new:
            continue
        e = AtlasEdge(
            id=uuid.uuid4(),
            graph_id=g.id,
            from_node_id=from_new,
            to_node_id=to_new,
            label=e_dict.get("label", "related_to")[:255] or "related_to",
            description=e_dict.get("description", "")[:5000],
            cardinality_from=e_dict.get("cardinality_from"),
            cardinality_to=e_dict.get("cardinality_to"),
            is_directed=bool(e_dict.get("is_directed", True)),
            properties=e_dict.get("properties") or {},
            source=e_dict.get("source", "user")[:40],
            confidence=e_dict.get("confidence"),
        )
        db.add(e)

    await _bump_version(db, g, recount=True)
    version = g.version
    await db.commit()
    return success({"restored": True, "version": version})


@router.get("/graphs/{graph_id}/export")
async def export_graph(
    graph_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    format: str = "json-ld",
) -> Response:
    """Export the graph as JSON-LD or plain JSON, streamed so size does not matter."""
    g = await _load_graph(db, graph_id, user)
    if isinstance(g, JSONResponse):
        return g
    gid = g.id
    meta = _graph_meta(g)
    fname = (
        "".join(c if c.isalnum() else "_" for c in (g.name or "atlas"))[:60] or "atlas"
    )
    suffix = "jsonld" if format != "json" else "json"
    # the stream opens its own session and this one must not sit idle under it
    await db.close()
    return StreamingResponse(
        _export_stream(gid, meta, format),
        media_type="application/ld+json" if format != "json" else "application/json",
        headers={"Content-Disposition": f'attachment; filename="{fname}.{suffix}"'},
    )


async def _export_stream(gid: uuid.UUID, meta: dict[str, Any], format: str):
    import json as _json

    from sqlalchemy.orm import aliased

    from app.core.deps import async_session

    def dump(value: Any) -> str:
        return _json.dumps(value, default=str)

    def iri(label: str) -> str:
        slug = "".join(c if c.isalnum() else "_" for c in label.strip())
        return f"atlas:{gid}#{slug}"

    kinds = {
        AtlasNodeKind.CONCEPT: "owl:Class",
        AtlasNodeKind.INSTANCE: "owl:NamedIndividual",
        AtlasNodeKind.DOCUMENT: "rdfs:Resource",
        AtlasNodeKind.PROPERTY: "owl:DatatypeProperty",
    }
    from_node, to_node = aliased(AtlasNode), aliased(AtlasNode)
    node_query = (
        select(AtlasNode)
        .where(AtlasNode.graph_id == gid)
        .execution_options(yield_per=1000)
    )
    edge_query = (
        select(AtlasEdge, from_node.label, to_node.label)
        .join(from_node, from_node.id == AtlasEdge.from_node_id)
        .join(to_node, to_node.id == AtlasEdge.to_node_id)
        .where(AtlasEdge.graph_id == gid)
        .execution_options(yield_per=1000)
    )
    async with async_session() as session:
        if format == "json":
            yield '{"graph": ' + dump(meta) + ', "nodes": ['
            first = True
            async for n in await session.stream_scalars(node_query):
                yield ("" if first else ",") + dump(_node_to_dict(n))
                first = False
            yield '], "edges": ['
            first = True
            async for e, _a, _b in await session.stream(edge_query):
                yield ("" if first else ",") + dump(_edge_to_dict(e))
                first = False
            yield "]}"
            return
        context = {
            "atlas": f"https://abenix/atlas/{gid}#",
            "owl": "http://www.w3.org/2002/07/owl#",
            "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
        }
        yield '{"@context": ' + dump(context) + ', "@graph": ['
        first = True
        async for n in await session.stream_scalars(node_query):
            item = {
                "@id": iri(n.label),
                "@type": kinds.get(n.kind, "owl:Class"),
                "rdfs:label": n.label,
                "rdfs:comment": n.description or "",
                "atlas:properties": n.properties or {},
            }
            yield ("" if first else ",") + dump(item)
            first = False
        async for e, from_label, to_label in await session.stream(edge_query):
            item = {
                "@id": f"atlas:{gid}#edge_{e.id}",
                "@type": "owl:ObjectProperty",
                "rdfs:label": e.label,
                "rdfs:domain": {"@id": iri(from_label)},
                "rdfs:range": {"@id": iri(to_label)},
                "atlas:cardinality_from": e.cardinality_from,
                "atlas:cardinality_to": e.cardinality_to,
            }
            yield ("" if first else ",") + dump(item)
            first = False
        yield '], "atlas:meta": ' + dump(meta) + "}"


async def _load_kb(
    db: AsyncSession,
    kb_id: str | uuid.UUID,
    user: User,
) -> KnowledgeBase | None:
    """KB the caller can read, else None."""
    from app.services.kb_access import user_can_access_collection

    try:
        kid = uuid.UUID(str(kb_id))
    except (TypeError, ValueError):
        return None
    kb = (
        await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == kid))
    ).scalar_one_or_none()
    if not kb or not await user_can_access_collection(db, user=user, kb=kb):
        return None
    return kb


async def _embed_texts(texts: list[str]) -> list[list[float]] | None:
    """OpenAI embeddings, returns None if the API key is unset."""
    import os

    api_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not api_key or not texts:
        return None
    try:
        import openai

        client = openai.AsyncOpenAI(api_key=api_key)
        resp = await client.embeddings.create(
            model="text-embedding-3-small",
            input=texts,
        )
        return [d.embedding for d in resp.data]
    except Exception as e:
        logger.warning("Atlas embedding call failed: %s", e)
        return None


def _project_2d(embeddings: list[list[float]]) -> list[tuple[float, float]]:
    """Project N×D embeddings to N×2 via random projection."""
    import random

    rng = random.Random(1729)
    d = len(embeddings[0]) if embeddings else 0
    if d == 0:
        return [(0.0, 0.0) for _ in embeddings]
    rx = [rng.gauss(0.0, 1.0) for _ in range(d)]
    ry = [rng.gauss(0.0, 1.0) for _ in range(d)]
    pts: list[tuple[float, float]] = []
    for emb in embeddings:
        x = sum(a * b for a, b in zip(emb, rx))
        y = sum(a * b for a, b in zip(emb, ry))
        pts.append((x, y))
    return pts


def _normalise_to_canvas(
    pts: list[tuple[float, float]],
    cx: float = 480,
    cy: float = 320,
    span: float = 720,
) -> list[tuple[float, float]]:
    """Map an arbitrary 2D scatter onto a `span × span` canvas centered
    at `(cx, cy)`. Stable + reproducible for any input range."""
    if not pts:
        return pts
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)
    rx = max(maxx - minx, 1e-6)
    ry = max(maxy - miny, 1e-6)
    out: list[tuple[float, float]] = []
    for x, y in pts:
        nx = (x - minx) / rx - 0.5
        ny = (y - miny) / ry - 0.5
        out.append((round(cx + nx * span, 1), round(cy + ny * span, 1)))
    return out


@router.post("/graphs/{graph_id}/bind-kb")
async def bind_kb(
    graph_id: str,
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Bind / unbind an Atlas graph to a knowledge collection."""
    g = await _load_graph(db, graph_id, user, need="edit")
    if isinstance(g, JSONResponse):
        return g
    new_kb_id_raw = body.get("kb_id")
    if new_kb_id_raw is None:
        g.kb_id = None
    else:
        kb = await _load_kb(db, new_kb_id_raw, user)
        if not kb:
            return error("Knowledge base not found", 404)
        g.kb_id = kb.id
    if isinstance(body.get("governs_extraction"), bool):
        g.settings = {
            **(g.settings or {}),
            "governs_extraction": body["governs_extraction"],
        }
    if body.get("ontology_mode") in ("strict", "guided"):
        g.settings = {**(g.settings or {}), "ontology_mode": body["ontology_mode"]}
    await _bump_version(db, g)
    await db.commit()
    await db.refresh(g)
    return success({"graph": _graph_meta(g)})


_SYNC_TASKS: set[asyncio.Task] = set()
_SYNC_RUNNING = "running"
_SYNC_STALE = timedelta(minutes=10)


def _doc_node_values(
    graph_id: uuid.UUID, kb: Any, row: Any, index: int
) -> dict[str, Any]:
    status = row.status.value if hasattr(row.status, "value") else str(row.status)
    now = datetime.now(timezone.utc)
    return {
        "id": uuid.uuid4(),
        "graph_id": graph_id,
        "label": row.filename[:255],
        "kind": AtlasNodeKind.DOCUMENT,
        "description": (
            f"Imported from KB {kb['name']} · {row.file_type} · {row.file_size or 0} bytes"
        ),
        "properties": {
            "kb_id": str(kb["id"]),
            "kb_name": kb["name"],
            "file_type": row.file_type,
            "file_size": row.file_size,
            "status": status,
        },
        "document_id": row.id,
        "source": "kb_sync",
        "confidence": 1.0,
        "tags": ["kb-doc"],
        "position_x": 80.0 + (index % 6) * 220,
        "position_y": 80.0 + (index // 6) * 160,
        "created_at": now,
        "updated_at": now,
        "recorded_at": now,
    }


def _unsynced_documents(graph_id: uuid.UUID, kb_id: uuid.UUID, after: uuid.UUID | None):
    q = (
        select(
            Document.id,
            Document.filename,
            Document.file_type,
            Document.file_size,
            Document.status,
        )
        .where(
            Document.kb_id == kb_id,
            ~select(AtlasNode.id)
            .where(AtlasNode.graph_id == graph_id, AtlasNode.document_id == Document.id)
            .exists(),
        )
        .order_by(Document.id)
    )
    return q.where(Document.id > after) if after else q


async def _sync_batches(
    db: AsyncSession,
    g: AtlasGraph,
    kb: dict[str, Any],
    user_id: uuid.UUID,
    on_batch=None,
    max_batches: int | None = None,
) -> tuple[int, list[uuid.UUID]]:
    """Insert document nodes a batch per transaction. A rerun continues where this stopped."""
    imported = 0
    created: list[uuid.UUID] = []
    after: uuid.UUID | None = None
    start = g.node_count or 0
    batches = 0
    while max_batches is None or batches < max_batches:
        rows = (
            await db.execute(
                _unsynced_documents(g.id, kb["id"], after).limit(SYNC_BATCH)
            )
        ).all()
        if not rows:
            break
        values = [
            _doc_node_values(g.id, kb, row, start + imported + i)
            for i, row in enumerate(rows)
        ]
        await db.execute(insert(AtlasNode), values)
        created += [v["id"] for v in values]
        imported += len(rows)
        after = rows[-1].id
        await _bump_version(db, g, nodes=len(rows))
        if on_batch:
            await on_batch(imported)
        await db.commit()
        batches += 1
        if len(rows) < SYNC_BATCH:
            break
    return imported, created


async def _run_kb_sync(
    graph_id: uuid.UUID, kb: dict[str, Any], user_id: uuid.UUID, total: int
) -> None:
    from app.core.deps import bg_session

    async with bg_session() as db:
        g = (
            await db.execute(select(AtlasGraph).where(AtlasGraph.id == graph_id))
        ).scalar_one()

        async def progress(imported: int) -> None:
            await _set_sync_state(
                db, g, status=_SYNC_RUNNING, imported=imported, total=total
            )

        try:
            imported, _ = await _sync_batches(db, g, kb, user_id, on_batch=progress)
            await atlas_snapshots.capture(
                db, g, user_id, label=f"sync-kb {kb['name']}", meta=_graph_meta(g)
            )
            await _set_sync_state(
                db, g, status="complete", imported=imported, total=total, error=None
            )
            await db.commit()
        except Exception as e:
            logger.exception("atlas kb sync failed for %s", graph_id)
            await db.rollback()
            await _set_sync_state(db, g, status="failed", error=str(e)[:500])
            await db.commit()


async def _set_sync_state(db: AsyncSession, g: AtlasGraph, **state: Any) -> None:
    await db.execute(
        text(
            "UPDATE atlas_graphs SET settings = "
            "coalesce(settings, '{}'::jsonb) || jsonb_build_object('kb_sync', "
            "coalesce(settings->'kb_sync', '{}'::jsonb) || CAST(:state AS jsonb)) "
            "WHERE id = :g"
        ),
        {
            "g": g.id,
            "state": json.dumps(
                {**state, "updated_at": datetime.now(timezone.utc).isoformat()}
            ),
        },
    )


def _sync_is_running(g: AtlasGraph) -> bool:
    state = (g.settings or {}).get("kb_sync") or {}
    if state.get("status") != _SYNC_RUNNING:
        return False
    try:
        stamp = datetime.fromisoformat(state.get("updated_at") or "")
    except ValueError:
        return False
    return datetime.now(timezone.utc) - stamp < _SYNC_STALE


@router.post("/graphs/{graph_id}/sync-kb")
async def sync_kb(
    graph_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Project the bound KB's documents onto the canvas, in the background when there are many."""
    g = await _load_graph(db, graph_id, user, need="edit")
    if isinstance(g, JSONResponse):
        return g
    if not g.kb_id:
        return error("Graph is not bound to a knowledge collection", 400)
    kb_row = await _load_kb(db, g.kb_id, user)
    if not kb_row:
        return error("Bound KB no longer exists or is inaccessible", 404)
    kb = {"id": kb_row.id, "name": kb_row.name}

    if _sync_is_running(g):
        return success(
            {
                "graph": _graph_meta(g),
                "imported": 0,
                "skipped": 0,
                "created_nodes": [],
                "queued": True,
                "sync": (g.settings or {}).get("kb_sync"),
            }
        )

    missing = (
        await db.execute(
            select(func.count()).select_from(
                _unsynced_documents(g.id, kb["id"], None).order_by(None).subquery()
            )
        )
    ).scalar() or 0
    total = (
        await db.execute(
            select(func.count()).select_from(Document).where(Document.kb_id == kb["id"])
        )
    ).scalar() or 0

    if missing > SYNC_INLINE_DOCS:
        await _set_sync_state(db, g, status=_SYNC_RUNNING, imported=0, total=missing)
        await db.commit()
        await db.refresh(g)
        task = asyncio.create_task(_run_kb_sync(g.id, kb, user.id, missing))
        _SYNC_TASKS.add(task)
        task.add_done_callback(_SYNC_TASKS.discard)
        return success(
            {
                "graph": _graph_meta(g),
                "imported": 0,
                "skipped": total - missing,
                "created_nodes": [],
                "queued": True,
                "sync": (g.settings or {}).get("kb_sync"),
            }
        )

    imported, created_ids = await _sync_batches(db, g, kb, user.id)
    if imported:
        await _maybe_snapshot(db, g, user.id, label=f"sync-kb {kb['name']}")
    else:
        await _bump_version(db, g)
    await db.commit()
    await db.refresh(g)
    created = (
        (await db.execute(select(AtlasNode).where(AtlasNode.id.in_(created_ids))))
        .scalars()
        .all()
        if created_ids
        else []
    )
    return success(
        {
            "graph": _graph_meta(g),
            "imported": imported,
            "skipped": total - imported,
            "created_nodes": [_node_to_dict(n) for n in created],
            "queued": False,
        }
    )


@router.get("/graphs/{graph_id}/sync-kb")
async def sync_kb_status(
    graph_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    g = await _load_graph(db, graph_id, user)
    if isinstance(g, JSONResponse):
        return g
    return success(
        {"sync": (g.settings or {}).get("kb_sync"), "running": _sync_is_running(g)}
    )


@router.post("/graphs/{graph_id}/query")
async def visual_query(
    graph_id: str,
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Match a small graph pattern, each pattern's candidates fetched and capped in SQL."""
    g = await _load_graph(db, graph_id, user)
    if isinstance(g, JSONResponse):
        return g
    patterns = body.get("patterns") or []
    traversals = body.get("traversals") or []
    limit = max(1, min(int(body.get("limit") or 50), 200))
    if not isinstance(patterns, list) or not patterns:
        return error("At least one pattern is required", 400)

    async def pattern_candidates(p: dict) -> list[AtlasNode]:
        q = select(AtlasNode).where(AtlasNode.graph_id == g.id)
        like = (p.get("label_like") or "").lower().strip()
        if like:
            escaped = like.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            q = q.where(func.lower(AtlasNode.label).like(f"%{escaped}%", escape="\\"))
        kind = p.get("kind")
        if kind:
            try:
                q = q.where(AtlasNode.kind == AtlasNodeKind(kind))
            except ValueError:
                return []
        return list(
            (
                await db.execute(
                    q.order_by(AtlasNode.created_at, AtlasNode.id).limit(
                        QUERY_CANDIDATES
                    )
                )
            )
            .scalars()
            .all()
        )

    try:
        await _read_guard(db)
        cand_lists = [await pattern_candidates(p) for p in patterns]
        ids = list({n.id for c in cand_lists for n in c})
        edges = (
            list(
                (
                    await db.execute(
                        select(AtlasEdge).where(
                            AtlasEdge.graph_id == g.id,
                            AtlasEdge.from_node_id.in_(ids),
                            AtlasEdge.to_node_id.in_(ids),
                        )
                    )
                )
                .scalars()
                .all()
            )
            if traversals and ids
            else []
        )
    except DBAPIError as e:
        await db.rollback()
        logger.warning("atlas query failed: %s", e)
        return _too_slow()

    edge_index_fwd: dict[tuple[uuid.UUID, uuid.UUID], list[AtlasEdge]] = {}
    for e in edges:
        edge_index_fwd.setdefault((e.from_node_id, e.to_node_id), []).append(e)

    def edge_match(
        from_node: AtlasNode, to_node: AtlasNode, like: str
    ) -> AtlasEdge | None:
        like_l = (like or "").lower().strip()
        for e in edge_index_fwd.get((from_node.id, to_node.id), []):
            if not like_l or like_l in e.label.lower():
                return e
        return None

    matches: list[dict[str, Any]] = []
    steps = 0

    def backtrack(i: int, picked: list[AtlasNode]) -> None:
        nonlocal steps
        steps += 1
        if len(matches) >= limit or steps > QUERY_STEPS:
            return
        if i == len(patterns):
            ok = True
            edge_payload: list[dict[str, Any]] = []
            for t in traversals:
                a = picked[int(t.get("from_idx", 0))]
                b = picked[int(t.get("to_idx", 0))]
                em = edge_match(a, b, t.get("label_like") or "")
                if not em:
                    ok = False
                    break
                edge_payload.append(_edge_to_dict(em))
            if ok:
                matches.append(
                    {
                        "nodes": [_node_to_dict(n) for n in picked],
                        "edges": edge_payload,
                    }
                )
            return
        for c in cand_lists[i]:
            if c in picked:
                continue
            picked.append(c)
            backtrack(i + 1, picked)
            picked.pop()

    backtrack(0, [])

    return success(
        {
            "matches": matches,
            "count": len(matches),
            "limit": limit,
            "truncated": steps > QUERY_STEPS
            or any(len(c) >= QUERY_CANDIDATES for c in cand_lists),
        }
    )


@router.patch("/graphs/{graph_id}/nodes/{node_id}/binding")
async def patch_binding(
    graph_id: str,
    node_id: str,
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Bind a node to a live data source."""
    g = await _load_graph(db, graph_id, user, need="edit")
    if isinstance(g, JSONResponse):
        return g
    try:
        nid = uuid.UUID(node_id)
    except ValueError:
        return error("Invalid node id", 400)
    n = (
        await db.execute(
            select(AtlasNode).where(AtlasNode.id == nid, AtlasNode.graph_id == g.id)
        )
    ).scalar_one_or_none()
    if not n:
        return error("Node not found", 404)

    binding = body.get("binding")
    props = dict(n.properties or {})
    if binding is None:
        props.pop("_binding", None)
    else:
        if not isinstance(binding, dict) or not binding.get("kind"):
            return error("binding.kind is required", 400)
        if binding["kind"] in ("kb_collection", "kb_documents"):
            kb = await _load_kb(db, binding.get("ref_id") or "", user)
            if not kb:
                return error("Bound KB not found or not in your tenant", 404)
        props["_binding"] = binding
    n.properties = props
    n.updated_at = datetime.now(timezone.utc)
    await _bump_version(db, g)
    await db.commit()
    await db.refresh(n)
    return success({"node": _node_to_dict(n)})


@router.get("/graphs/{graph_id}/nodes/{node_id}/instances")
async def get_instances(
    graph_id: str,
    node_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = 25,
) -> JSONResponse:
    """Return live instances for a bound node."""
    g = await _load_graph(db, graph_id, user)
    if isinstance(g, JSONResponse):
        return g
    try:
        nid = uuid.UUID(node_id)
    except ValueError:
        return error("Invalid node id", 400)
    n = (
        await db.execute(
            select(AtlasNode).where(AtlasNode.id == nid, AtlasNode.graph_id == g.id)
        )
    ).scalar_one_or_none()
    if not n:
        return error("Node not found", 404)
    binding = (n.properties or {}).get("_binding")
    if not binding or not isinstance(binding, dict):
        return success({"instances": [], "binding": None, "count": 0})

    kind = binding.get("kind")
    instances: list[dict[str, Any]] = []
    total = 0
    if kind in ("kb_collection", "kb_documents"):
        kb = await _load_kb(db, binding.get("ref_id") or "", user)
        if kb:
            docs = (
                (
                    await db.execute(
                        select(Document)
                        .where(Document.kb_id == kb.id)
                        .limit(min(max(limit, 1), 200))
                    )
                )
                .scalars()
                .all()
            )
            total = kb.doc_count or len(docs)
            instances = [
                {
                    "id": str(d.id),
                    "label": d.filename,
                    "file_type": d.file_type,
                    "file_size": d.file_size,
                    "status": (
                        d.status.value if hasattr(d.status, "value") else str(d.status)
                    ),
                    "kb_id": str(d.kb_id),
                }
                for d in docs
            ]
    return success({"binding": binding, "instances": instances, "count": total})


# Curated kits — small enough to ship inline, large enough to demo.
# Each kit is a list of nodes + edges in the same shape `apply_ops`
# already accepts, so import is one transaction with no special code.
ATLAS_STARTERS: dict[str, dict[str, Any]] = {
    "fibo-core": {
        "name": "FIBO Core (Financial)",
        "description": "Top-level financial industry concepts. Counterparties, instruments, markets, agreements.",
        "ops": [
            {
                "op": "add_node",
                "label": "Counterparty",
                "kind": "concept",
                "description": "Legal entity participating in a financial transaction",
            },
            {
                "op": "add_node",
                "label": "LegalEntity",
                "kind": "concept",
                "description": "Organisation with rights and obligations",
            },
            {
                "op": "add_node",
                "label": "Account",
                "kind": "concept",
                "description": "Financial holding container",
            },
            {
                "op": "add_node",
                "label": "Trade",
                "kind": "concept",
                "description": "Concluded transaction",
            },
            {
                "op": "add_node",
                "label": "Order",
                "kind": "concept",
                "description": "Instruction to trade",
            },
            {
                "op": "add_node",
                "label": "Instrument",
                "kind": "concept",
                "description": "Tradable financial asset",
            },
            {
                "op": "add_node",
                "label": "Quote",
                "kind": "concept",
                "description": "Price observation",
            },
            {
                "op": "add_node",
                "label": "Market",
                "kind": "concept",
                "description": "Venue where instruments trade",
            },
            {
                "op": "add_node",
                "label": "Settlement",
                "kind": "concept",
                "description": "Final transfer of obligations",
            },
            {
                "op": "add_node",
                "label": "Position",
                "kind": "concept",
                "description": "Net exposure to an instrument",
            },
            {
                "op": "add_edge",
                "from": "Counterparty",
                "to": "LegalEntity",
                "label": "is_a",
                "cardinality_from": "*",
                "cardinality_to": "1",
            },
            {
                "op": "add_edge",
                "from": "Counterparty",
                "to": "Account",
                "label": "holds",
                "cardinality_from": "1",
                "cardinality_to": "*",
            },
            {
                "op": "add_edge",
                "from": "Trade",
                "to": "Counterparty",
                "label": "between",
                "cardinality_from": "1..*",
                "cardinality_to": "2",
            },
            {
                "op": "add_edge",
                "from": "Order",
                "to": "Trade",
                "label": "produces",
                "cardinality_from": "1",
                "cardinality_to": "0..1",
            },
            {
                "op": "add_edge",
                "from": "Trade",
                "to": "Instrument",
                "label": "references",
                "cardinality_from": "*",
                "cardinality_to": "1",
            },
            {
                "op": "add_edge",
                "from": "Quote",
                "to": "Instrument",
                "label": "prices",
                "cardinality_from": "*",
                "cardinality_to": "1",
            },
            {
                "op": "add_edge",
                "from": "Order",
                "to": "Market",
                "label": "routed_to",
                "cardinality_from": "*",
                "cardinality_to": "1",
            },
            {
                "op": "add_edge",
                "from": "Trade",
                "to": "Settlement",
                "label": "settles_via",
                "cardinality_from": "1",
                "cardinality_to": "1",
            },
            {
                "op": "add_edge",
                "from": "Position",
                "to": "Account",
                "label": "held_in",
                "cardinality_from": "*",
                "cardinality_to": "1",
            },
            {
                "op": "add_edge",
                "from": "Position",
                "to": "Instrument",
                "label": "of",
                "cardinality_from": "*",
                "cardinality_to": "1",
            },
        ],
    },
    "fix": {
        "name": "FIX Protocol",
        "description": "Order-flow primitives from the FIX standard. Order, ExecutionReport, Symbol, Party.",
        "ops": [
            {
                "op": "add_node",
                "label": "Order",
                "kind": "concept",
                "description": "FIX Order (NewOrderSingle)",
            },
            {
                "op": "add_node",
                "label": "ExecutionReport",
                "kind": "concept",
                "description": "FIX ExecutionReport (8)",
            },
            {
                "op": "add_node",
                "label": "Symbol",
                "kind": "concept",
                "description": "FIX Symbol (55)",
            },
            {
                "op": "add_node",
                "label": "Party",
                "kind": "concept",
                "description": "FIX Parties (NoPartyIDs)",
            },
            {
                "op": "add_node",
                "label": "OrderQty",
                "kind": "property",
                "description": "FIX OrderQty (38)",
            },
            {
                "op": "add_node",
                "label": "Price",
                "kind": "property",
                "description": "FIX Price (44)",
            },
            {
                "op": "add_edge",
                "from": "Order",
                "to": "Symbol",
                "label": "for_symbol",
                "cardinality_from": "*",
                "cardinality_to": "1",
            },
            {
                "op": "add_edge",
                "from": "Order",
                "to": "Party",
                "label": "involves",
                "cardinality_from": "*",
                "cardinality_to": "1..*",
            },
            {
                "op": "add_edge",
                "from": "ExecutionReport",
                "to": "Order",
                "label": "reports_on",
                "cardinality_from": "*",
                "cardinality_to": "1",
            },
            {
                "op": "add_edge",
                "from": "Order",
                "to": "OrderQty",
                "label": "has_quantity",
                "cardinality_from": "1",
                "cardinality_to": "1",
            },
            {
                "op": "add_edge",
                "from": "Order",
                "to": "Price",
                "label": "has_price",
                "cardinality_from": "1",
                "cardinality_to": "0..1",
            },
        ],
    },
    "emir": {
        "name": "EMIR Reporting",
        "description": "EMIR trade-reporting concepts. Reportable trade, parties, UTI/UPI, lifecycle events.",
        "ops": [
            {
                "op": "add_node",
                "label": "ReportableTrade",
                "kind": "concept",
                "description": "Derivative trade subject to EMIR Article 9 reporting",
            },
            {
                "op": "add_node",
                "label": "ReportingCounterparty",
                "kind": "concept",
                "description": "Entity submitting the report",
            },
            {
                "op": "add_node",
                "label": "OtherCounterparty",
                "kind": "concept",
                "description": "Counterparty to the trade",
            },
            {
                "op": "add_node",
                "label": "TradeRepository",
                "kind": "concept",
                "description": "Authorised destination for EMIR reports",
            },
            {
                "op": "add_node",
                "label": "UTI",
                "kind": "property",
                "description": "Unique Trade Identifier",
            },
            {
                "op": "add_node",
                "label": "UPI",
                "kind": "property",
                "description": "Unique Product Identifier",
            },
            {
                "op": "add_node",
                "label": "LifecycleEvent",
                "kind": "concept",
                "description": "Modify/terminate/early-termination event on a trade",
            },
            {
                "op": "add_edge",
                "from": "ReportableTrade",
                "to": "ReportingCounterparty",
                "label": "reported_by",
                "cardinality_from": "1",
                "cardinality_to": "1",
            },
            {
                "op": "add_edge",
                "from": "ReportableTrade",
                "to": "OtherCounterparty",
                "label": "with",
                "cardinality_from": "1",
                "cardinality_to": "1",
            },
            {
                "op": "add_edge",
                "from": "ReportableTrade",
                "to": "TradeRepository",
                "label": "submitted_to",
                "cardinality_from": "*",
                "cardinality_to": "1",
            },
            {
                "op": "add_edge",
                "from": "ReportableTrade",
                "to": "UTI",
                "label": "identified_by",
                "cardinality_from": "1",
                "cardinality_to": "1",
            },
            {
                "op": "add_edge",
                "from": "ReportableTrade",
                "to": "UPI",
                "label": "classified_as",
                "cardinality_from": "*",
                "cardinality_to": "1",
            },
            {
                "op": "add_edge",
                "from": "LifecycleEvent",
                "to": "ReportableTrade",
                "label": "modifies",
                "cardinality_from": "*",
                "cardinality_to": "1",
            },
        ],
    },
    "isda": {
        "name": "ISDA Master Agreement",
        "description": "ISDA documentation hierarchy. Master agreement, schedule, CSA, confirmation.",
        "ops": [
            {
                "op": "add_node",
                "label": "MasterAgreement",
                "kind": "concept",
                "description": "ISDA Master Agreement",
            },
            {
                "op": "add_node",
                "label": "Schedule",
                "kind": "concept",
                "description": "Modifications to the Master form",
            },
            {
                "op": "add_node",
                "label": "CreditSupportAnnex",
                "kind": "concept",
                "description": "Collateral / margining terms",
            },
            {
                "op": "add_node",
                "label": "Confirmation",
                "kind": "concept",
                "description": "Terms of an individual transaction",
            },
            {
                "op": "add_node",
                "label": "Termination",
                "kind": "concept",
                "description": "Early termination event",
            },
            {
                "op": "add_node",
                "label": "Counterparty",
                "kind": "concept",
                "description": "Party to the agreement",
            },
            {
                "op": "add_edge",
                "from": "Schedule",
                "to": "MasterAgreement",
                "label": "amends",
                "cardinality_from": "1",
                "cardinality_to": "1",
            },
            {
                "op": "add_edge",
                "from": "CreditSupportAnnex",
                "to": "MasterAgreement",
                "label": "annexed_to",
                "cardinality_from": "0..1",
                "cardinality_to": "1",
            },
            {
                "op": "add_edge",
                "from": "Confirmation",
                "to": "MasterAgreement",
                "label": "governed_by",
                "cardinality_from": "*",
                "cardinality_to": "1",
            },
            {
                "op": "add_edge",
                "from": "MasterAgreement",
                "to": "Counterparty",
                "label": "between",
                "cardinality_from": "*",
                "cardinality_to": "2",
            },
            {
                "op": "add_edge",
                "from": "Termination",
                "to": "MasterAgreement",
                "label": "terminates",
                "cardinality_from": "0..1",
                "cardinality_to": "1",
            },
        ],
    },
    "etrm-eod": {
        "name": "ETRM EOD Workflow",
        "description": "Endur/Murex end-of-day pipeline primitives. Use as starting point for Murex/Endur copilot work.",
        "ops": [
            {
                "op": "add_node",
                "label": "TradeBook",
                "kind": "concept",
                "description": "Set of trades booked under one logical owner",
            },
            {
                "op": "add_node",
                "label": "EODBatch",
                "kind": "concept",
                "description": "End-of-day computational pipeline run",
            },
            {
                "op": "add_node",
                "label": "MarketDataSnapshot",
                "kind": "concept",
                "description": "Curve/price snapshot used in the batch",
            },
            {
                "op": "add_node",
                "label": "PnLReport",
                "kind": "concept",
                "description": "Output P&L statement",
            },
            {
                "op": "add_node",
                "label": "RiskReport",
                "kind": "concept",
                "description": "VAR / PFE / sensitivities output",
            },
            {
                "op": "add_node",
                "label": "ReconBreak",
                "kind": "concept",
                "description": "Mismatch between systems requiring resolution",
            },
            {
                "op": "add_node",
                "label": "Operator",
                "kind": "concept",
                "description": "Person or agent investigating the batch",
            },
            {
                "op": "add_edge",
                "from": "EODBatch",
                "to": "TradeBook",
                "label": "processes",
                "cardinality_from": "1",
                "cardinality_to": "*",
            },
            {
                "op": "add_edge",
                "from": "EODBatch",
                "to": "MarketDataSnapshot",
                "label": "consumes",
                "cardinality_from": "1",
                "cardinality_to": "1..*",
            },
            {
                "op": "add_edge",
                "from": "EODBatch",
                "to": "PnLReport",
                "label": "produces",
                "cardinality_from": "1",
                "cardinality_to": "1",
            },
            {
                "op": "add_edge",
                "from": "EODBatch",
                "to": "RiskReport",
                "label": "produces",
                "cardinality_from": "1",
                "cardinality_to": "1",
            },
            {
                "op": "add_edge",
                "from": "EODBatch",
                "to": "ReconBreak",
                "label": "may_emit",
                "cardinality_from": "1",
                "cardinality_to": "*",
            },
            {
                "op": "add_edge",
                "from": "Operator",
                "to": "ReconBreak",
                "label": "resolves",
                "cardinality_from": "*",
                "cardinality_to": "*",
            },
        ],
    },
}


@router.get("/starters")
async def list_starters(
    user: User = Depends(get_current_user),
) -> JSONResponse:
    """Catalogue of starter ontologies. Cheap — no DB hit."""
    return success(
        {
            "starters": [
                {
                    "id": kid,
                    "name": kit["name"],
                    "description": kit["description"],
                    "node_count": sum(1 for o in kit["ops"] if o["op"] == "add_node"),
                    "edge_count": sum(1 for o in kit["ops"] if o["op"] == "add_edge"),
                }
                for kid, kit in ATLAS_STARTERS.items()
            ],
        }
    )


@router.post("/graphs/{graph_id}/import-starter")
async def import_starter(
    graph_id: str,
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Import a curated starter ontology into the graph."""
    g = await _load_graph(db, graph_id, user, need="edit")
    if isinstance(g, JSONResponse):
        return g
    kit_id = (body.get("kit") or "").strip()
    kit = ATLAS_STARTERS.get(kit_id)
    if not kit:
        return error(f"Unknown starter kit: {kit_id}", 404)

    # Mark every op so the canvas can render them as `starter`-sourced
    # (renders subtly to distinguish from extracted vs hand-drawn).
    enriched = []
    for o in kit["ops"]:
        enriched.append({**o, "source": f"starter:{kit_id}"})

    # Reuse the apply route's logic without going through HTTP.
    apply_resp = await apply_ops(
        graph_id=graph_id, body={"ops": enriched, "auto_layout": True}, user=user, db=db
    )
    return apply_resp


async def _relayout_in_sql(
    db: AsyncSession, g: AtlasGraph, user: User, mode: str
) -> JSONResponse:
    """A big graph is laid out in one statement and the canvas reloads its window."""
    count = g.node_count or 0
    if mode == "circle":
        position = (
            "480 + (260 + 14 * :count) * cos(2 * pi() * o.i / :count)",
            "320 + (260 + 14 * :count) * sin(2 * pi() * o.i / :count)",
        )
    else:
        # embedding every node of a graph this size is not a layout decision to take here
        mode = "grid"
        position = (
            "80 + (o.i % ceil(sqrt(:count))::int) * 240",
            "80 + floor(o.i / ceil(sqrt(:count)))::int * 180",
        )
    await db.execute(
        text(
            f"""
            UPDATE atlas_nodes n SET position_x = {position[0]}, position_y = {position[1]},
                updated_at = now()
            FROM (SELECT id, row_number() OVER (ORDER BY created_at, id) - 1 AS i
                  FROM atlas_nodes WHERE graph_id = :g) o
            WHERE n.id = o.id
            """
        ),
        {"g": g.id, "count": count},
    )
    await _bump_version(db, g)
    await _maybe_snapshot(db, g, user.id, label=f"relayout {mode}")
    await db.commit()
    await db.refresh(g)
    return success(
        {
            "relaid_out": count,
            "mode": mode,
            "graph": _graph_meta(g),
            "nodes": [],
            "reload": True,
        }
    )


@router.post("/graphs/{graph_id}/relayout")
async def relayout(
    graph_id: str,
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Reposition every node on the canvas."""
    import math

    g = await _load_graph(db, graph_id, user, need="edit")
    if isinstance(g, JSONResponse):
        return g
    mode = (body.get("mode") or "semantic").lower()
    if (g.node_count or 0) > FULL_GRAPH_LIMIT:
        return await _relayout_in_sql(db, g, user, mode)
    nodes = (
        (
            await db.execute(
                select(AtlasNode)
                .where(AtlasNode.graph_id == g.id)
                .order_by(AtlasNode.created_at)
            )
        )
        .scalars()
        .all()
    )
    if not nodes:
        return success({"relaid_out": 0, "mode": mode, "graph": _graph_meta(g)})

    if mode == "semantic":
        texts = [
            (
                f"{n.label}. {n.description or ''} "
                f"{' '.join(f'{k}={v}' for k, v in (n.properties or {}).items() if k != '_binding')}"
            ).strip()
            for n in nodes
        ]
        embeddings = await _embed_texts(texts)
        if embeddings is None:
            mode = "circle"  # graceful degradation
        else:
            pts = _project_2d(embeddings)
            normalised = _normalise_to_canvas(pts)
            for n, (x, y) in zip(nodes, normalised):
                n.position_x = x
                n.position_y = y

    if mode == "circle":
        cx, cy = 480, 320
        radius = 260 + 14 * len(nodes)
        for i, n in enumerate(nodes):
            theta = (2 * math.pi * i) / len(nodes)
            n.position_x = round(cx + radius * math.cos(theta), 1)
            n.position_y = round(cy + radius * math.sin(theta), 1)

    if mode == "grid":
        cols = max(1, int(math.ceil(math.sqrt(len(nodes)))))
        for i, n in enumerate(nodes):
            n.position_x = round(80 + (i % cols) * 240, 1)
            n.position_y = round(80 + (i // cols) * 180, 1)

    await _bump_version(db, g)
    await _maybe_snapshot(db, g, user.id, label=f"relayout {mode}")
    await db.commit()
    await db.refresh(g)
    return success(
        {
            "relaid_out": len(nodes),
            "mode": mode,
            "graph": _graph_meta(g),
            "nodes": [_node_to_dict(n) for n in nodes],
        }
    )


@router.post("/graphs/{graph_id}/persist-to-kb")
async def persist_to_kb(
    graph_id: str,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """If the graph is bound to a KB, write the dropped file into the"""
    g = await _load_graph(db, graph_id, user, need="edit")
    if isinstance(g, JSONResponse):
        return g
    if not g.kb_id:
        return error("Graph is not bound to a knowledge collection", 400)
    kb = await _load_kb(db, g.kb_id, user)
    if not kb:
        return error("Bound KB not found", 404)

    raw = await file.read()
    if not raw:
        return error("Empty file", 400)
    if len(raw) > 50 * 1024 * 1024:
        return error("Upload exceeds 50 MB", 413)

    from app.services.kb_quota import quota_error

    refused = await quota_error(db, user.tenant_id, add_documents=1, add_bytes=len(raw))
    if refused is not None:
        return refused

    fn = file.filename or "atlas-upload"
    ext = fn.rsplit(".", 1)[-1].lower() if "." in fn else "txt"
    doc_id = uuid.uuid4()
    safe = f"{doc_id}.{ext}"
    storage_url = ""
    try:
        from engine.storage import get_storage  # type: ignore

        storage = get_storage()
        storage_url = await storage.upload(
            tenant_id=str(user.tenant_id),
            path=f"kb/{kb.id}/{safe}",
            data=raw,
            content_type=file.content_type or "application/octet-stream",
        )
    except Exception as e:
        logger.warning("Atlas KB persist storage failed (%s) — using local path", e)
        from pathlib import Path as _P

        upload_dir = _P("/tmp") / str(user.tenant_id) / str(kb.id)
        upload_dir.mkdir(parents=True, exist_ok=True)
        (upload_dir / safe).write_bytes(raw)
        storage_url = str(upload_dir / safe)

    from models.knowledge_base import DocumentStatus  # type: ignore

    doc = Document(
        id=doc_id,
        kb_id=kb.id,
        filename=fn,
        file_type=ext,
        file_size=len(raw),
        chunk_count=0,
        status=DocumentStatus.PROCESSING,
        storage_url=storage_url,
        uploaded_by=user.id,
    )
    db.add(doc)
    kb.doc_count = (kb.doc_count or 0) + 1
    await db.commit()
    await db.refresh(doc)
    return success(
        {
            "document": {
                "id": str(doc.id),
                "kb_id": str(doc.kb_id),
                "filename": doc.filename,
                "file_type": doc.file_type,
                "file_size": doc.file_size,
            },
        }
    )


async def _context_kb(
    db: AsyncSession, g: AtlasGraph, user: User
) -> KnowledgeBase | JSONResponse:
    if not g.kb_id:
        return error(
            "Bind this atlas to a knowledge collection first, then run Cognify on it.",
            400,
        )
    kb = await _load_kb(db, g.kb_id, user)
    if not kb:
        return error("Bound KB no longer exists or is inaccessible", 404)
    return kb


async def _hidden_documents(user: User, kb_id: uuid.UUID) -> list[str]:
    """The same document ACL search applies, an entity only from hidden documents stays hidden."""
    from engine.knowledge.document_acl import hidden_for_search

    role = getattr(user.role, "value", str(user.role))
    return sorted(
        await hidden_for_search([str(kb_id)], user_id=str(user.id), user_role=role)
    )


@router.get("/graphs/{graph_id}/context")
async def context_graph(
    graph_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """The enterprise context graph for this atlas, the ontology with its live entity counts."""
    g = await _load_graph(db, graph_id, user)
    if isinstance(g, JSONResponse):
        return g
    settings = g.settings or {}
    out: dict[str, Any] = {
        "graph_id": str(g.id),
        "kb_id": str(g.kb_id) if g.kb_id else None,
        "governs_extraction": settings.get("governs_extraction", True),
        "ontology_mode": settings.get("ontology_mode", "strict"),
        "bound": False,
        "concepts": [],
    }
    if not g.kb_id:
        return success(out)
    kb = await _load_kb(db, g.kb_id, user)
    if not kb:
        return success(out)
    out.update(
        bound=True,
        kb_name=kb.name,
        last_cognified_at=(
            kb.last_cognified_at.isoformat() if kb.last_cognified_at else None
        ),
    )
    await _read_guard(db)
    concepts = (
        await db.execute(
            select(AtlasNode.id, AtlasNode.label)
            .where(AtlasNode.graph_id == g.id, AtlasNode.kind == AtlasNodeKind.CONCEPT)
            .order_by(AtlasNode.label)
            .limit(500)
        )
    ).all()
    counts = (
        await db.execute(
            text(
                "SELECT atlas_concept_id, entity_type, count(*) FROM graph_entities "
                "WHERE kb_id = :kb GROUP BY 1, 2"
            ),
            {"kb": kb.id},
        )
    ).all()
    by_concept: dict[Any, int] = {}
    by_type: dict[str, int] = {}
    unmapped = 0
    for concept_id, entity_type, n in counts:
        by_type[entity_type] = by_type.get(entity_type, 0) + n
        if concept_id:
            by_concept[concept_id] = by_concept.get(concept_id, 0) + n
        else:
            unmapped += n
    out["concepts"] = [
        {"id": str(c[0]), "label": c[1], "entity_count": by_concept.get(c[0], 0)}
        for c in concepts
    ]
    out["entity_count"] = sum(by_type.values())
    out["mapped_entities"] = sum(by_concept.values())
    out["unmapped_entities"] = unmapped
    out["entities_by_type"] = by_type
    out["relationship_count"] = (
        await db.execute(
            text("SELECT count(*) FROM graph_relationships WHERE kb_id = :kb"),
            {"kb": kb.id},
        )
    ).scalar() or 0
    job = (
        await db.execute(
            text(
                "SELECT id, status, chunks_processed, chunks_total, cost_usd, "
                "off_ontology_dropped, stop_reason, created_at FROM cognify_jobs "
                "WHERE kb_id = :kb ORDER BY created_at DESC LIMIT 1"
            ),
            {"kb": kb.id},
        )
    ).first()
    if job:
        out["latest_job"] = {
            "id": str(job[0]),
            "status": str(job[1]).lower(),
            "chunks_processed": job[2],
            "chunks_total": job[3],
            "cost_usd": float(job[4] or 0),
            "off_ontology_dropped": job[5],
            "stop_reason": job[6],
            "created_at": job[7].isoformat() if job[7] else None,
        }
    try:
        from engine.knowledge.neo4j_client import concept_counts

        live = await asyncio.wait_for(
            concept_counts(str(kb.id), str(user.tenant_id)), timeout=5
        )
        out["neo4j_available"] = True
        out["neo4j_entity_count"] = live["total"]
    except Exception as e:
        logger.info("context graph live count unavailable: %s", e)
        out["neo4j_available"] = False
    return success(out)


@router.get("/graphs/{graph_id}/entities")
async def browse_context_entities(
    graph_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    concept_id: str | None = None,
    entity_type: str | None = None,
    q: str | None = None,
    after: str = "",
    limit: int = 50,
) -> JSONResponse:
    """Real instances from Neo4j, by Atlas concept, by type or by name."""
    g = await _load_graph(db, graph_id, user)
    if isinstance(g, JSONResponse):
        return g
    kb = await _context_kb(db, g, user)
    if isinstance(kb, JSONResponse):
        return kb
    type_name = entity_type
    if concept_id:
        try:
            concept = uuid.UUID(concept_id)
        except ValueError:
            return error("Invalid concept id", 400)
        node = (
            await db.execute(
                select(AtlasNode.label).where(
                    AtlasNode.id == concept, AtlasNode.graph_id == g.id
                )
            )
        ).scalar_one_or_none()
        if node is None:
            return error("Concept not found in this atlas", 404)
        type_name = type_name or node
    from engine.knowledge.neo4j_client import browse_entities

    try:
        page = await browse_entities(
            str(kb.id),
            tenant_id=str(user.tenant_id),
            entity_type=type_name,
            concept_id=concept_id,
            query=q,
            after=after,
            limit=limit,
            hidden=await _hidden_documents(user, kb.id),
        )
    except Exception as e:
        logger.warning("context graph browse failed: %s", e)
        return error(
            "Neo4j did not answer. The entity counts on this page still come from Postgres.",
            503,
        )
    return success({**page, "kb_id": str(kb.id), "source": "neo4j"})


@router.get("/graphs/{graph_id}/entities/neighbourhood")
async def context_entity_neighbourhood(
    graph_id: str,
    name: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
    relationship: str | None = None,
) -> JSONResponse:
    """One real entity and the entities it relates to."""
    g = await _load_graph(db, graph_id, user)
    if isinstance(g, JSONResponse):
        return g
    kb = await _context_kb(db, g, user)
    if isinstance(kb, JSONResponse):
        return kb
    from engine.knowledge.neo4j_client import entity_neighbourhood

    try:
        hood = await entity_neighbourhood(
            str(kb.id),
            name,
            tenant_id=str(user.tenant_id),
            limit=limit,
            relationship=relationship,
            hidden=await _hidden_documents(user, kb.id),
        )
    except Exception as e:
        logger.warning("context graph neighbourhood failed: %s", e)
        return error("Neo4j did not answer. Try again in a moment.", 503)
    if hood["entity"] is None:
        return error("Entity not found", 404)
    return success({**hood, "kb_id": str(kb.id), "source": "neo4j"})


@router.post("/graphs/{graph_id}/entities/query")
async def query_context_entities(
    graph_id: str,
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Entities of one concept related to entities of another, read from Neo4j."""
    g = await _load_graph(db, graph_id, user)
    if isinstance(g, JSONResponse):
        return g
    kb = await _context_kb(db, g, user)
    if isinstance(kb, JSONResponse):
        return kb
    from engine.knowledge.neo4j_client import query_entities

    try:
        rows = await query_entities(
            str(kb.id),
            tenant_id=str(user.tenant_id),
            from_type=body.get("from"),
            relationship=body.get("relationship"),
            to_type=body.get("to"),
            name=body.get("name"),
            limit=int(body.get("limit") or 50),
            hidden=await _hidden_documents(user, kb.id),
        )
    except Exception as e:
        logger.warning("context graph query failed: %s", e)
        return error("Neo4j did not answer. Try again in a moment.", 503)
    return success({"matches": rows, "count": len(rows), "source": "neo4j"})
