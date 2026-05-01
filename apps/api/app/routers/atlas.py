"""Atlas — unified ontology + knowledge-base canvas."""
from __future__ import annotations

import io
import logging
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.responses import error, success

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))
from models.atlas import AtlasEdge, AtlasGraph, AtlasNode, AtlasNodeKind, AtlasSnapshot  # type: ignore
from models.knowledge_base import Document, KnowledgeBase  # type: ignore
from models.user import User  # type: ignore

# Reuses the BPM analyser's hardened multimodal pipeline.
from app.routers.bpm_analyzer import (  # type: ignore
    _build_anthropic_messages,
    _parse_agent_specs,
    _process_upload,
    _provider_for,
    _run_vision_model,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/atlas", tags=["atlas"])


def _node_to_dict(n: AtlasNode) -> dict[str, Any]:
    return {
        "id": str(n.id),
        "graph_id": str(n.graph_id),
        "label": n.label,
        "kind": n.kind.value if hasattr(n.kind, "value") else str(n.kind),
        "description": n.description or "",
        "properties": n.properties or {},
        "position": {"x": n.position_x, "y": n.position_y} if n.position_x is not None else None,
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


def _graph_meta(g: AtlasGraph) -> dict[str, Any]:
    return {
        "id": str(g.id),
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


async def _load_graph(
    db: AsyncSession, graph_id: str, user: User,
) -> AtlasGraph | JSONResponse:
    """Fetch a graph + tenant check. Returns the graph or an error response."""
    try:
        gid = uuid.UUID(graph_id)
    except ValueError:
        return error("Invalid graph id", 400)
    g = (await db.execute(select(AtlasGraph).where(AtlasGraph.id == gid))).scalar_one_or_none()
    if not g:
        return error("Graph not found", 404)
    if g.tenant_id != user.tenant_id:
        return error("Forbidden", 403)
    return g


async def _bump_version(db: AsyncSession, graph: AtlasGraph) -> None:
    """Bump version + refresh counts. Runs in the caller's transaction."""
    node_count = (await db.execute(
        select(AtlasNode).where(AtlasNode.graph_id == graph.id)
    )).all()
    edge_count = (await db.execute(
        select(AtlasEdge).where(AtlasEdge.graph_id == graph.id)
    )).all()
    graph.node_count = len(node_count)
    graph.edge_count = len(edge_count)
    graph.version = (graph.version or 0) + 1
    graph.updated_at = datetime.now(timezone.utc)


async def _maybe_snapshot(
    db: AsyncSession, graph: AtlasGraph, user_id: uuid.UUID, *, label: str | None = None,
) -> None:
    """Snapshot the graph, rate-limited to one per 60s per graph."""
    last = (await db.execute(
        select(AtlasSnapshot)
        .where(AtlasSnapshot.graph_id == graph.id)
        .order_by(desc(AtlasSnapshot.created_at))
        .limit(1)
    )).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if last and last.created_at and (now - last.created_at) < timedelta(seconds=60):
        return
    nodes = (await db.execute(
        select(AtlasNode).where(AtlasNode.graph_id == graph.id)
    )).scalars().all()
    edges = (await db.execute(
        select(AtlasEdge).where(AtlasEdge.graph_id == graph.id)
    )).scalars().all()
    snap = AtlasSnapshot(
        id=uuid.uuid4(),
        graph_id=graph.id,
        version=graph.version,
        label=label,
        created_by=user_id,
        auto=label is None,
        payload={
            "graph": _graph_meta(graph),
            "nodes": [_node_to_dict(n) for n in nodes],
            "edges": [_edge_to_dict(e) for e in edges],
        },
    )
    db.add(snap)


@router.get("/graphs")
async def list_graphs(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = 100,
) -> JSONResponse:
    """List Atlas graphs the caller's tenant can see."""
    rows = (await db.execute(
        select(AtlasGraph)
        .where(AtlasGraph.tenant_id == user.tenant_id)
        .order_by(desc(AtlasGraph.updated_at))
        .limit(min(max(limit, 1), 200))
    )).scalars().all()
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
    return success({"graph": _graph_meta(g)})


@router.get("/graphs/{graph_id}")
async def get_graph(
    graph_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Full graph snapshot — meta + every node + every edge."""
    g = await _load_graph(db, graph_id, user)
    if isinstance(g, JSONResponse):
        return g
    nodes = (await db.execute(
        select(AtlasNode).where(AtlasNode.graph_id == g.id).order_by(AtlasNode.created_at)
    )).scalars().all()
    edges = (await db.execute(
        select(AtlasEdge).where(AtlasEdge.graph_id == g.id).order_by(AtlasEdge.created_at)
    )).scalars().all()
    return success({
        "graph": _graph_meta(g),
        "nodes": [_node_to_dict(n) for n in nodes],
        "edges": [_edge_to_dict(e) for e in edges],
    })


@router.patch("/graphs/{graph_id}")
async def patch_graph(
    graph_id: str,
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    g = await _load_graph(db, graph_id, user)
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
    g = await _load_graph(db, graph_id, user)
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
    g = await _load_graph(db, graph_id, user)
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
    await _bump_version(db, g)
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
    g = await _load_graph(db, graph_id, user)
    if isinstance(g, JSONResponse):
        return g
    try:
        nid = uuid.UUID(node_id)
    except ValueError:
        return error("Invalid node id", 400)
    n = (await db.execute(
        select(AtlasNode).where(AtlasNode.id == nid, AtlasNode.graph_id == g.id)
    )).scalar_one_or_none()
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
    g = await _load_graph(db, graph_id, user)
    if isinstance(g, JSONResponse):
        return g
    try:
        nid = uuid.UUID(node_id)
    except ValueError:
        return error("Invalid node id", 400)
    n = (await db.execute(
        select(AtlasNode).where(AtlasNode.id == nid, AtlasNode.graph_id == g.id)
    )).scalar_one_or_none()
    if not n:
        return error("Node not found", 404)
    await db.delete(n)
    await _bump_version(db, g)
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
    g = await _load_graph(db, graph_id, user)
    if isinstance(g, JSONResponse):
        return g
    try:
        from_id = uuid.UUID(body.get("from_node_id"))
        to_id = uuid.UUID(body.get("to_node_id"))
    except (TypeError, ValueError):
        return error("from_node_id and to_node_id must be UUIDs", 400)
    nodes = (await db.execute(
        select(AtlasNode).where(
            AtlasNode.graph_id == g.id, AtlasNode.id.in_([from_id, to_id])
        )
    )).scalars().all()
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
    await _bump_version(db, g)
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
    g = await _load_graph(db, graph_id, user)
    if isinstance(g, JSONResponse):
        return g
    try:
        eid = uuid.UUID(edge_id)
    except ValueError:
        return error("Invalid edge id", 400)
    e = (await db.execute(
        select(AtlasEdge).where(AtlasEdge.id == eid, AtlasEdge.graph_id == g.id)
    )).scalar_one_or_none()
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
    g = await _load_graph(db, graph_id, user)
    if isinstance(g, JSONResponse):
        return g
    try:
        eid = uuid.UUID(edge_id)
    except ValueError:
        return error("Invalid edge id", 400)
    e = (await db.execute(
        select(AtlasEdge).where(AtlasEdge.id == eid, AtlasEdge.graph_id == g.id)
    )).scalar_one_or_none()
    if not e:
        return error("Edge not found", 404)
    await db.delete(e)
    await _bump_version(db, g)
    await db.commit()
    return success({"deleted": True})


_NL_SYSTEM_PROMPT = (
    "You are Atlas — an ontology editor. The user types natural-language "
    "sentences about a domain; you turn each sentence into a structured "
    "list of graph operations.\n\n"
    "Supported operations (always emit a JSON object with exactly an "
    "`agents` field which is an array of these — the field name is "
    "fixed for parser compatibility, but each item is an op record):\n"
    "  { \"op\": \"add_node\", \"label\": \"<concept>\", "
    "\"kind\": \"concept|instance|document|property\", "
    "\"description\": \"<optional>\", \"tags\": [\"<optional>\"] }\n"
    "  { \"op\": \"add_edge\", \"from\": \"<source label>\", \"to\": \"<target label>\", "
    "\"label\": \"<verb>\", \"cardinality_from\": \"1|0..1|*|1..*\", "
    "\"cardinality_to\": \"1|0..1|*|1..*\", \"description\": \"<optional>\" }\n\n"
    "Rules:\n"
    "  * If a concept is referenced but not yet defined, emit an "
    "`add_node` for it before the `add_edge`.\n"
    "  * Infer cardinality from natural words: `has many`, `each`, "
    "`exactly one`, `optional`, `multiple`.\n"
    "  * Default verb when none given: `related_to`.\n"
    "  * For \"X has Y\" with no quantifier, default cardinality_from=1, "
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
    g = await _load_graph(db, graph_id, user)
    if isinstance(g, JSONResponse):
        return g
    text = (body.get("text") or "").strip()
    if not text:
        return error("text is required", 400)
    model = (body.get("model") or "gemini-2.5-pro").strip()

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
        return error("Could not parse the sentence into operations — try "
                     "a different phrasing or a stronger model", 502)
    return success({
        "ops": parsed["agents"],
        "model": meta.get("model") or model,
        "cost": meta.get("cost", 0.0),
        "duration_ms": meta.get("duration_ms", 0),
    })


_EXTRACT_SYSTEM_PROMPT = (
    "You are Atlas Extractor. The user has uploaded a document, image, "
    "audio recording, video, or text. Your job is to read it and "
    "propose an ontology fragment — concepts, relationships, key "
    "properties — that captures the domain it describes.\n\n"
    "Reply with PURE JSON only, in this exact shape (the field name "
    "`agents` is required for parser compatibility, but each entry is "
    "an op):\n"
    "  {\"agents\": [\n"
    "    {\"op\": \"add_node\", \"label\": \"<TitleCase concept>\", "
    "\"kind\": \"concept\", \"description\": \"<one line>\", "
    "\"properties\": {<typed attributes>}, \"confidence\": 0.0..1.0},\n"
    "    {\"op\": \"add_edge\", \"from\": \"<source label>\", \"to\": "
    "\"<target label>\", \"label\": \"<snake_case verb>\", "
    "\"cardinality_from\": \"1|0..1|*|1..*\", "
    "\"cardinality_to\": \"1|0..1|*|1..*\", \"confidence\": 0.0..1.0}\n"
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
    g = await _load_graph(db, graph_id, user)
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
                raw, file.content_type or "", file.filename or "",
            )
        except Exception as e:
            logger.exception("Atlas extract upload processing failed")
            return error(f"Could not process upload: {e}", 415)
    elif text.strip():
        attachments = [{
            "type": "text_doc",
            "text": text[:200000],
            "filename": "user-input.txt",
            "doc_kind": "txt",
        }]
    else:
        return error("Provide either a file or text", 400)

    chosen_model = (model or "").strip() or "gemini-2.5-pro"
    if required_provider and _provider_for(chosen_model) != required_provider:
        chosen_model = "gemini-2.5-pro"

    seed = "Read the attached artefact and propose an ontology fragment."
    msgs = _build_anthropic_messages(
        attachments, history_turns=[], new_user_question=seed,
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
        return error("Extractor could not produce parseable proposals — "
                     "try a different model or simplify the source", 502)

    return success({
        "ops": parsed["agents"],
        "model": meta.get("model") or chosen_model,
        "cost": meta.get("cost", 0.0),
        "duration_ms": meta.get("duration_ms", 0),
        "primary_type": attachments[0].get("type") if attachments else None,
    })


@router.post("/graphs/{graph_id}/apply")
async def apply_ops(
    graph_id: str,
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Apply a list of ops returned from parse-nl or extract."""
    g = await _load_graph(db, graph_id, user)
    if isinstance(g, JSONResponse):
        return g

    ops = body.get("ops") or []
    if not isinstance(ops, list):
        return error("ops must be an array", 400)
    auto_layout = bool(body.get("auto_layout", True))

    # Pre-load existing nodes by lowercase label so we can dedupe
    # across the import (extractor often references a label that the
    # user already drew).
    existing_nodes = (await db.execute(
        select(AtlasNode).where(AtlasNode.graph_id == g.id)
    )).scalars().all()
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
        existing_pos = [
            (n.position_x, n.position_y)
            for n in existing_nodes if n.position_x is not None and n.position_y is not None
        ]
        if existing_pos:
            cx = sum(p[0] for p in existing_pos) / len(existing_pos)
            cy = sum(p[1] for p in existing_pos) / len(existing_pos)
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

    await _bump_version(db, g)
    await _maybe_snapshot(db, g, user.id, label="ops apply")
    await db.commit()
    await db.refresh(g)
    return success({
        "graph": _graph_meta(g),
        "created_nodes": [_node_to_dict(n) for n in created_nodes],
        "created_edges": [_edge_to_dict(e) for e in created_edges],
        "skipped": skipped,
    })


def _suggestions_for_graph(
    nodes: list[AtlasNode], edges: list[AtlasEdge],
) -> list[dict[str, Any]]:
    """Heuristic-only suggestion engine."""
    out: list[dict[str, Any]] = []

    # 1. Possible duplicate nodes by case-insensitive prefix match
    by_lower = {n.label.lower(): n for n in nodes}
    seen_pairs: set[tuple[str, str]] = set()
    for a in nodes:
        la = a.label.lower()
        for b in nodes:
            if a.id == b.id:
                continue
            lb = b.label.lower()
            if (lb, la) in seen_pairs:
                continue
            if la and lb and (la in lb or lb in la) and abs(len(la) - len(lb)) <= 4 and la != lb:
                seen_pairs.add((la, lb))
                out.append({
                    "kind": "possible_duplicate",
                    "title": f"`{a.label}` and `{b.label}` look similar",
                    "detail": "Same prefix or substring — consider merging or "
                              "renaming one of them so the ontology stays terse.",
                    "node_ids": [str(a.id), str(b.id)],
                    "severity": "info",
                })
                if len(out) > 30:
                    return out

    # 2. Missing inverse edges
    edge_pairs = {(str(e.from_node_id), str(e.to_node_id), e.label) for e in edges}
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
                out.append({
                    "kind": "missing_inverse",
                    "title": f"`{e.label}` has no inverse on `{to_node.label}`",
                    "detail": (f"Add an edge from `{to_node.label}` to "
                               f"`{from_node.label}` so the graph is "
                               "navigable in both directions."),
                    "edge_id": str(e.id),
                    "from_node_id": str(e.from_node_id),
                    "to_node_id": str(e.to_node_id),
                    "severity": "info",
                })
                if len(out) > 30:
                    return out

    # 3. Concepts with zero edges (orphans)
    connected = {e.from_node_id for e in edges} | {e.to_node_id for e in edges}
    for n in nodes:
        if n.kind != AtlasNodeKind.CONCEPT:
            continue
        if n.id not in connected:
            out.append({
                "kind": "orphan_node",
                "title": f"`{n.label}` is disconnected",
                "detail": "No edges connect this concept. Either delete it "
                          "or relate it to something so it earns its place.",
                "node_ids": [str(n.id)],
                "severity": "warning",
            })
            if len(out) > 30:
                break

    # 4. Edges that drop their cardinality on both sides
    missing_card = [e for e in edges if not e.cardinality_from and not e.cardinality_to]
    if len(missing_card) >= 3:
        out.append({
            "kind": "missing_cardinalities",
            "title": f"{len(missing_card)} edges have no cardinality",
            "detail": "Add cardinalities (`1`, `0..1`, `*`, `1..*`) so "
                      "constraint validation can run.",
            "edge_ids": [str(e.id) for e in missing_card[:20]],
            "severity": "info",
        })

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
    nodes = (await db.execute(
        select(AtlasNode).where(AtlasNode.graph_id == g.id)
    )).scalars().all()
    edges = (await db.execute(
        select(AtlasEdge).where(AtlasEdge.graph_id == g.id)
    )).scalars().all()
    return success({"suggestions": _suggestions_for_graph(list(nodes), list(edges))})


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
    rows = (await db.execute(
        select(AtlasSnapshot)
        .where(AtlasSnapshot.graph_id == g.id)
        .order_by(desc(AtlasSnapshot.created_at))
        .limit(min(max(limit, 1), 500))
    )).scalars().all()
    return success({
        "snapshots": [
            {
                "id": str(s.id),
                "version": s.version,
                "label": s.label,
                "auto": s.auto,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            } for s in rows
        ],
    })


@router.post("/graphs/{graph_id}/snapshots")
async def capture_snapshot(
    graph_id: str,
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Manual snapshot: not rate-limited, labelled by the user."""
    g = await _load_graph(db, graph_id, user)
    if isinstance(g, JSONResponse):
        return g
    nodes = (await db.execute(
        select(AtlasNode).where(AtlasNode.graph_id == g.id)
    )).scalars().all()
    edges = (await db.execute(
        select(AtlasEdge).where(AtlasEdge.graph_id == g.id)
    )).scalars().all()
    snap = AtlasSnapshot(
        id=uuid.uuid4(),
        graph_id=g.id,
        version=g.version,
        label=(body.get("label") or "manual checkpoint")[:255],
        created_by=user.id,
        auto=False,
        payload={
            "graph": _graph_meta(g),
            "nodes": [_node_to_dict(n) for n in nodes],
            "edges": [_edge_to_dict(e) for e in edges],
        },
    )
    db.add(snap)
    await db.commit()
    await db.refresh(snap)
    return success({"id": str(snap.id), "version": snap.version})


@router.post("/graphs/{graph_id}/snapshots/{snapshot_id}/restore")
async def restore_snapshot(
    graph_id: str,
    snapshot_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Replay a snapshot: wipe live nodes/edges, recreate from payload."""
    g = await _load_graph(db, graph_id, user)
    if isinstance(g, JSONResponse):
        return g
    try:
        sid = uuid.UUID(snapshot_id)
    except ValueError:
        return error("Invalid snapshot id", 400)
    snap = (await db.execute(
        select(AtlasSnapshot).where(
            AtlasSnapshot.id == sid, AtlasSnapshot.graph_id == g.id,
        )
    )).scalar_one_or_none()
    if not snap:
        return error("Snapshot not found", 404)

    # Save the current state first.
    await _maybe_snapshot(db, g, user.id, label="pre-restore")

    # Clear live tables.
    nodes = (await db.execute(
        select(AtlasNode).where(AtlasNode.graph_id == g.id)
    )).scalars().all()
    edges = (await db.execute(
        select(AtlasEdge).where(AtlasEdge.graph_id == g.id)
    )).scalars().all()
    for e in edges:
        await db.delete(e)
    for n in nodes:
        await db.delete(n)
    await db.flush()

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

    await _bump_version(db, g)
    await db.commit()
    return success({"restored": True, "version": g.version})


@router.get("/graphs/{graph_id}/export")
async def export_graph(
    graph_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    format: str = "json-ld",
) -> Response:
    """Export the graph as JSON-LD or plain JSON."""
    g = await _load_graph(db, graph_id, user)
    if isinstance(g, JSONResponse):
        return g
    nodes = (await db.execute(
        select(AtlasNode).where(AtlasNode.graph_id == g.id)
    )).scalars().all()
    edges = (await db.execute(
        select(AtlasEdge).where(AtlasEdge.graph_id == g.id)
    )).scalars().all()

    def _iri(label: str) -> str:
        # Stable per-graph IRI; lowercased + space → underscore.
        slug = "".join(c if c.isalnum() else "_" for c in label.strip())
        return f"atlas:{g.id}#{slug}"

    if format == "json":
        body = {
            "graph": _graph_meta(g),
            "nodes": [_node_to_dict(n) for n in nodes],
            "edges": [_edge_to_dict(e) for e in edges],
        }
    else:
        # JSON-LD
        graph_arr: list[dict[str, Any]] = []
        for n in nodes:
            graph_arr.append({
                "@id": _iri(n.label),
                "@type": {
                    AtlasNodeKind.CONCEPT: "owl:Class",
                    AtlasNodeKind.INSTANCE: "owl:NamedIndividual",
                    AtlasNodeKind.DOCUMENT: "rdfs:Resource",
                    AtlasNodeKind.PROPERTY: "owl:DatatypeProperty",
                }.get(n.kind, "owl:Class"),
                "rdfs:label": n.label,
                "rdfs:comment": n.description or "",
                "atlas:properties": n.properties or {},
            })
        for e in edges:
            from_n = next((n for n in nodes if n.id == e.from_node_id), None)
            to_n = next((n for n in nodes if n.id == e.to_node_id), None)
            if not from_n or not to_n:
                continue
            graph_arr.append({
                "@id": f"atlas:{g.id}#edge_{e.id}",
                "@type": "owl:ObjectProperty",
                "rdfs:label": e.label,
                "rdfs:domain": {"@id": _iri(from_n.label)},
                "rdfs:range": {"@id": _iri(to_n.label)},
                "atlas:cardinality_from": e.cardinality_from,
                "atlas:cardinality_to": e.cardinality_to,
            })
        body = {
            "@context": {
                "atlas": f"https://abenix/atlas/{g.id}#",
                "owl": "http://www.w3.org/2002/07/owl#",
                "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
            },
            "@graph": graph_arr,
            "atlas:meta": _graph_meta(g),
        }

    fname = "".join(c if c.isalnum() else "_" for c in (g.name or "atlas"))[:60] or "atlas"
    suffix = "jsonld" if format != "json" else "json"
    return Response(
        content=__import__("json").dumps(body, indent=2, default=str),
        media_type="application/ld+json" if format != "json" else "application/json",
        headers={"Content-Disposition": f'attachment; filename="{fname}.{suffix}"'},
    )


async def _load_kb(
    db: AsyncSession, kb_id: str | uuid.UUID, user: User,
) -> KnowledgeBase | None:
    """Tenant-scoped KB load — returns None if not found / not owned."""
    try:
        kid = uuid.UUID(str(kb_id))
    except (TypeError, ValueError):
        return None
    kb = (await db.execute(
        select(KnowledgeBase).where(KnowledgeBase.id == kid)
    )).scalar_one_or_none()
    if not kb or kb.tenant_id != user.tenant_id:
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
            model="text-embedding-3-small", input=texts,
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
    pts: list[tuple[float, float]], cx: float = 480, cy: float = 320, span: float = 720,
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
    g = await _load_graph(db, graph_id, user)
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
    await _bump_version(db, g)
    await db.commit()
    await db.refresh(g)
    return success({"graph": _graph_meta(g)})


@router.post("/graphs/{graph_id}/sync-kb")
async def sync_kb(
    graph_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Project the bound KB's documents into the canvas as document"""
    g = await _load_graph(db, graph_id, user)
    if isinstance(g, JSONResponse):
        return g
    if not g.kb_id:
        return error("Graph is not bound to a knowledge collection", 400)
    kb = await _load_kb(db, g.kb_id, user)
    if not kb:
        return error("Bound KB no longer exists or is inaccessible", 404)

    docs = (await db.execute(
        select(Document).where(Document.kb_id == kb.id)
    )).scalars().all()

    existing_doc_ids: set[uuid.UUID] = {
        n.document_id for n in (await db.execute(
            select(AtlasNode).where(AtlasNode.graph_id == g.id, AtlasNode.document_id.is_not(None))
        )).scalars().all()
        if n.document_id
    }

    created: list[AtlasNode] = []
    cx, cy = 80.0, 80.0
    for i, d in enumerate(docs):
        if d.id in existing_doc_ids:
            continue
        n = AtlasNode(
            id=uuid.uuid4(),
            graph_id=g.id,
            label=d.filename[:255],
            kind=AtlasNodeKind.DOCUMENT,
            description=f"Imported from KB {kb.name} · {d.file_type} · {d.file_size or 0} bytes",
            properties={
                "kb_id": str(kb.id),
                "kb_name": kb.name,
                "file_type": d.file_type,
                "file_size": d.file_size,
                "status": d.status.value if hasattr(d.status, "value") else str(d.status),
            },
            document_id=d.id,
            source="kb_sync",
            confidence=1.0,
            tags=["kb-doc"],
            position_x=cx + (i % 6) * 220,
            position_y=cy + (i // 6) * 160,
        )
        db.add(n)
        created.append(n)

    await _bump_version(db, g)
    await _maybe_snapshot(db, g, user.id, label=f"sync-kb {kb.name}")
    await db.commit()
    await db.refresh(g)
    return success({
        "graph": _graph_meta(g),
        "imported": len(created),
        "skipped": len(docs) - len(created),
        "created_nodes": [_node_to_dict(n) for n in created],
    })


@router.post("/graphs/{graph_id}/query")
async def visual_query(
    graph_id: str,
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Match a small graph pattern."""
    g = await _load_graph(db, graph_id, user)
    if isinstance(g, JSONResponse):
        return g
    patterns = body.get("patterns") or []
    traversals = body.get("traversals") or []
    limit = max(1, min(int(body.get("limit") or 50), 200))
    if not isinstance(patterns, list) or not patterns:
        return error("At least one pattern is required", 400)

    nodes = (await db.execute(
        select(AtlasNode).where(AtlasNode.graph_id == g.id)
    )).scalars().all()
    edges = (await db.execute(
        select(AtlasEdge).where(AtlasEdge.graph_id == g.id)
    )).scalars().all()

    def pattern_candidates(p: dict) -> list[AtlasNode]:
        like = (p.get("label_like") or "").lower().strip()
        kind = p.get("kind")
        out = []
        for n in nodes:
            if like and like not in n.label.lower():
                continue
            if kind and (n.kind.value if hasattr(n.kind, "value") else str(n.kind)) != kind:
                continue
            out.append(n)
        return out

    cand_lists = [pattern_candidates(p) for p in patterns]

    edge_index_fwd: dict[tuple[uuid.UUID, uuid.UUID], list[AtlasEdge]] = {}
    for e in edges:
        edge_index_fwd.setdefault((e.from_node_id, e.to_node_id), []).append(e)

    def edge_match(from_node: AtlasNode, to_node: AtlasNode, like: str) -> AtlasEdge | None:
        like_l = (like or "").lower().strip()
        for e in edge_index_fwd.get((from_node.id, to_node.id), []):
            if not like_l or like_l in e.label.lower():
                return e
        return None

    matches: list[dict[str, Any]] = []

    def backtrack(i: int, picked: list[AtlasNode]) -> None:
        if len(matches) >= limit:
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
                matches.append({
                    "nodes": [_node_to_dict(n) for n in picked],
                    "edges": edge_payload,
                })
            return
        for c in cand_lists[i]:
            if c in picked:
                continue
            picked.append(c)
            backtrack(i + 1, picked)
            picked.pop()

    backtrack(0, [])

    return success({
        "matches": matches,
        "count": len(matches),
        "limit": limit,
    })


@router.patch("/graphs/{graph_id}/nodes/{node_id}/binding")
async def patch_binding(
    graph_id: str,
    node_id: str,
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Bind a node to a live data source."""
    g = await _load_graph(db, graph_id, user)
    if isinstance(g, JSONResponse):
        return g
    try:
        nid = uuid.UUID(node_id)
    except ValueError:
        return error("Invalid node id", 400)
    n = (await db.execute(
        select(AtlasNode).where(AtlasNode.id == nid, AtlasNode.graph_id == g.id)
    )).scalar_one_or_none()
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
    n = (await db.execute(
        select(AtlasNode).where(AtlasNode.id == nid, AtlasNode.graph_id == g.id)
    )).scalar_one_or_none()
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
            docs = (await db.execute(
                select(Document).where(Document.kb_id == kb.id).limit(min(max(limit, 1), 200))
            )).scalars().all()
            total = kb.doc_count or len(docs)
            instances = [
                {
                    "id": str(d.id),
                    "label": d.filename,
                    "file_type": d.file_type,
                    "file_size": d.file_size,
                    "status": d.status.value if hasattr(d.status, "value") else str(d.status),
                    "kb_id": str(d.kb_id),
                } for d in docs
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
            {"op": "add_node", "label": "Counterparty", "kind": "concept", "description": "Legal entity participating in a financial transaction"},
            {"op": "add_node", "label": "LegalEntity", "kind": "concept", "description": "Organisation with rights and obligations"},
            {"op": "add_node", "label": "Account", "kind": "concept", "description": "Financial holding container"},
            {"op": "add_node", "label": "Trade", "kind": "concept", "description": "Concluded transaction"},
            {"op": "add_node", "label": "Order", "kind": "concept", "description": "Instruction to trade"},
            {"op": "add_node", "label": "Instrument", "kind": "concept", "description": "Tradable financial asset"},
            {"op": "add_node", "label": "Quote", "kind": "concept", "description": "Price observation"},
            {"op": "add_node", "label": "Market", "kind": "concept", "description": "Venue where instruments trade"},
            {"op": "add_node", "label": "Settlement", "kind": "concept", "description": "Final transfer of obligations"},
            {"op": "add_node", "label": "Position", "kind": "concept", "description": "Net exposure to an instrument"},
            {"op": "add_edge", "from": "Counterparty", "to": "LegalEntity", "label": "is_a", "cardinality_from": "*", "cardinality_to": "1"},
            {"op": "add_edge", "from": "Counterparty", "to": "Account", "label": "holds", "cardinality_from": "1", "cardinality_to": "*"},
            {"op": "add_edge", "from": "Trade", "to": "Counterparty", "label": "between", "cardinality_from": "1..*", "cardinality_to": "2"},
            {"op": "add_edge", "from": "Order", "to": "Trade", "label": "produces", "cardinality_from": "1", "cardinality_to": "0..1"},
            {"op": "add_edge", "from": "Trade", "to": "Instrument", "label": "references", "cardinality_from": "*", "cardinality_to": "1"},
            {"op": "add_edge", "from": "Quote", "to": "Instrument", "label": "prices", "cardinality_from": "*", "cardinality_to": "1"},
            {"op": "add_edge", "from": "Order", "to": "Market", "label": "routed_to", "cardinality_from": "*", "cardinality_to": "1"},
            {"op": "add_edge", "from": "Trade", "to": "Settlement", "label": "settles_via", "cardinality_from": "1", "cardinality_to": "1"},
            {"op": "add_edge", "from": "Position", "to": "Account", "label": "held_in", "cardinality_from": "*", "cardinality_to": "1"},
            {"op": "add_edge", "from": "Position", "to": "Instrument", "label": "of", "cardinality_from": "*", "cardinality_to": "1"},
        ],
    },
    "fix": {
        "name": "FIX Protocol",
        "description": "Order-flow primitives from the FIX standard. Order, ExecutionReport, Symbol, Party.",
        "ops": [
            {"op": "add_node", "label": "Order", "kind": "concept", "description": "FIX Order (NewOrderSingle)"},
            {"op": "add_node", "label": "ExecutionReport", "kind": "concept", "description": "FIX ExecutionReport (8)"},
            {"op": "add_node", "label": "Symbol", "kind": "concept", "description": "FIX Symbol (55)"},
            {"op": "add_node", "label": "Party", "kind": "concept", "description": "FIX Parties (NoPartyIDs)"},
            {"op": "add_node", "label": "OrderQty", "kind": "property", "description": "FIX OrderQty (38)"},
            {"op": "add_node", "label": "Price", "kind": "property", "description": "FIX Price (44)"},
            {"op": "add_edge", "from": "Order", "to": "Symbol", "label": "for_symbol", "cardinality_from": "*", "cardinality_to": "1"},
            {"op": "add_edge", "from": "Order", "to": "Party", "label": "involves", "cardinality_from": "*", "cardinality_to": "1..*"},
            {"op": "add_edge", "from": "ExecutionReport", "to": "Order", "label": "reports_on", "cardinality_from": "*", "cardinality_to": "1"},
            {"op": "add_edge", "from": "Order", "to": "OrderQty", "label": "has_quantity", "cardinality_from": "1", "cardinality_to": "1"},
            {"op": "add_edge", "from": "Order", "to": "Price", "label": "has_price", "cardinality_from": "1", "cardinality_to": "0..1"},
        ],
    },
    "emir": {
        "name": "EMIR Reporting",
        "description": "EMIR trade-reporting concepts. Reportable trade, parties, UTI/UPI, lifecycle events.",
        "ops": [
            {"op": "add_node", "label": "ReportableTrade", "kind": "concept", "description": "Derivative trade subject to EMIR Article 9 reporting"},
            {"op": "add_node", "label": "ReportingCounterparty", "kind": "concept", "description": "Entity submitting the report"},
            {"op": "add_node", "label": "OtherCounterparty", "kind": "concept", "description": "Counterparty to the trade"},
            {"op": "add_node", "label": "TradeRepository", "kind": "concept", "description": "Authorised destination for EMIR reports"},
            {"op": "add_node", "label": "UTI", "kind": "property", "description": "Unique Trade Identifier"},
            {"op": "add_node", "label": "UPI", "kind": "property", "description": "Unique Product Identifier"},
            {"op": "add_node", "label": "LifecycleEvent", "kind": "concept", "description": "Modify/terminate/early-termination event on a trade"},
            {"op": "add_edge", "from": "ReportableTrade", "to": "ReportingCounterparty", "label": "reported_by", "cardinality_from": "1", "cardinality_to": "1"},
            {"op": "add_edge", "from": "ReportableTrade", "to": "OtherCounterparty", "label": "with", "cardinality_from": "1", "cardinality_to": "1"},
            {"op": "add_edge", "from": "ReportableTrade", "to": "TradeRepository", "label": "submitted_to", "cardinality_from": "*", "cardinality_to": "1"},
            {"op": "add_edge", "from": "ReportableTrade", "to": "UTI", "label": "identified_by", "cardinality_from": "1", "cardinality_to": "1"},
            {"op": "add_edge", "from": "ReportableTrade", "to": "UPI", "label": "classified_as", "cardinality_from": "*", "cardinality_to": "1"},
            {"op": "add_edge", "from": "LifecycleEvent", "to": "ReportableTrade", "label": "modifies", "cardinality_from": "*", "cardinality_to": "1"},
        ],
    },
    "isda": {
        "name": "ISDA Master Agreement",
        "description": "ISDA documentation hierarchy. Master agreement, schedule, CSA, confirmation.",
        "ops": [
            {"op": "add_node", "label": "MasterAgreement", "kind": "concept", "description": "ISDA Master Agreement"},
            {"op": "add_node", "label": "Schedule", "kind": "concept", "description": "Modifications to the Master form"},
            {"op": "add_node", "label": "CreditSupportAnnex", "kind": "concept", "description": "Collateral / margining terms"},
            {"op": "add_node", "label": "Confirmation", "kind": "concept", "description": "Terms of an individual transaction"},
            {"op": "add_node", "label": "Termination", "kind": "concept", "description": "Early termination event"},
            {"op": "add_node", "label": "Counterparty", "kind": "concept", "description": "Party to the agreement"},
            {"op": "add_edge", "from": "Schedule", "to": "MasterAgreement", "label": "amends", "cardinality_from": "1", "cardinality_to": "1"},
            {"op": "add_edge", "from": "CreditSupportAnnex", "to": "MasterAgreement", "label": "annexed_to", "cardinality_from": "0..1", "cardinality_to": "1"},
            {"op": "add_edge", "from": "Confirmation", "to": "MasterAgreement", "label": "governed_by", "cardinality_from": "*", "cardinality_to": "1"},
            {"op": "add_edge", "from": "MasterAgreement", "to": "Counterparty", "label": "between", "cardinality_from": "*", "cardinality_to": "2"},
            {"op": "add_edge", "from": "Termination", "to": "MasterAgreement", "label": "terminates", "cardinality_from": "0..1", "cardinality_to": "1"},
        ],
    },
    "etrm-eod": {
        "name": "ETRM EOD Workflow",
        "description": "Endur/Murex end-of-day pipeline primitives. Use as starting point for Murex/Endur copilot work.",
        "ops": [
            {"op": "add_node", "label": "TradeBook", "kind": "concept", "description": "Set of trades booked under one logical owner"},
            {"op": "add_node", "label": "EODBatch", "kind": "concept", "description": "End-of-day computational pipeline run"},
            {"op": "add_node", "label": "MarketDataSnapshot", "kind": "concept", "description": "Curve/price snapshot used in the batch"},
            {"op": "add_node", "label": "PnLReport", "kind": "concept", "description": "Output P&L statement"},
            {"op": "add_node", "label": "RiskReport", "kind": "concept", "description": "VAR / PFE / sensitivities output"},
            {"op": "add_node", "label": "ReconBreak", "kind": "concept", "description": "Mismatch between systems requiring resolution"},
            {"op": "add_node", "label": "Operator", "kind": "concept", "description": "Person or agent investigating the batch"},
            {"op": "add_edge", "from": "EODBatch", "to": "TradeBook", "label": "processes", "cardinality_from": "1", "cardinality_to": "*"},
            {"op": "add_edge", "from": "EODBatch", "to": "MarketDataSnapshot", "label": "consumes", "cardinality_from": "1", "cardinality_to": "1..*"},
            {"op": "add_edge", "from": "EODBatch", "to": "PnLReport", "label": "produces", "cardinality_from": "1", "cardinality_to": "1"},
            {"op": "add_edge", "from": "EODBatch", "to": "RiskReport", "label": "produces", "cardinality_from": "1", "cardinality_to": "1"},
            {"op": "add_edge", "from": "EODBatch", "to": "ReconBreak", "label": "may_emit", "cardinality_from": "1", "cardinality_to": "*"},
            {"op": "add_edge", "from": "Operator", "to": "ReconBreak", "label": "resolves", "cardinality_from": "*", "cardinality_to": "*"},
        ],
    },
}


@router.get("/starters")
async def list_starters(
    user: User = Depends(get_current_user),
) -> JSONResponse:
    """Catalogue of starter ontologies. Cheap — no DB hit."""
    return success({
        "starters": [
            {"id": kid, "name": kit["name"], "description": kit["description"], "node_count": sum(1 for o in kit["ops"] if o["op"] == "add_node"), "edge_count": sum(1 for o in kit["ops"] if o["op"] == "add_edge")}
            for kid, kit in ATLAS_STARTERS.items()
        ],
    })


@router.post("/graphs/{graph_id}/import-starter")
async def import_starter(
    graph_id: str,
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Import a curated starter ontology into the graph."""
    g = await _load_graph(db, graph_id, user)
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
    apply_resp = await apply_ops(graph_id=graph_id, body={"ops": enriched, "auto_layout": True}, user=user, db=db)
    return apply_resp


@router.post("/graphs/{graph_id}/relayout")
async def relayout(
    graph_id: str,
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Reposition every node on the canvas."""
    import math

    g = await _load_graph(db, graph_id, user)
    if isinstance(g, JSONResponse):
        return g
    mode = (body.get("mode") or "semantic").lower()
    nodes = (await db.execute(
        select(AtlasNode).where(AtlasNode.graph_id == g.id).order_by(AtlasNode.created_at)
    )).scalars().all()
    if not nodes:
        return success({"relaid_out": 0, "mode": mode, "graph": _graph_meta(g)})

    if mode == "semantic":
        texts = [
            (f"{n.label}. {n.description or ''} "
             f"{' '.join(f'{k}={v}' for k, v in (n.properties or {}).items() if k != '_binding')}").strip()
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
    return success({
        "relaid_out": len(nodes),
        "mode": mode,
        "graph": _graph_meta(g),
        "nodes": [_node_to_dict(n) for n in nodes],
    })




@router.post("/graphs/{graph_id}/persist-to-kb")
async def persist_to_kb(
    graph_id: str,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """If the graph is bound to a KB, write the dropped file into the"""
    g = await _load_graph(db, graph_id, user)
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
    )
    db.add(doc)
    kb.doc_count = (kb.doc_count or 0) + 1
    await db.commit()
    await db.refresh(doc)
    return success({
        "document": {
            "id": str(doc.id),
            "kb_id": str(doc.kb_id),
            "filename": doc.filename,
            "file_type": doc.file_type,
            "file_size": doc.file_size,
        },
    })
