"""Talk-to-workflow shell — verb runtime."""
from __future__ import annotations

import copy
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.workflow_shell_grammar import GRAMMAR, list_verbs, verb_doc_md

logger = logging.getLogger(__name__)


def _get_pipeline_dsl(agent: Any) -> dict[str, Any]:
    cfg = agent.model_config_ or {}
    return {"pipeline_config": cfg.get("pipeline_config") or {"nodes": [], "edges": []}}


def _resolve_run_alias(alias: str, runs: list[Any]) -> Any | None:
    """'last' → runs[0], 'last-2' → runs[1], or just match by id."""
    if not alias:
        return None
    if alias.startswith("last"):
        offset = 0
        if alias == "last":
            offset = 0
        else:
            try:
                offset = int(alias.split("-", 1)[1]) - 1
            except Exception:
                offset = 0
        if 0 <= offset < len(runs):
            return runs[offset]
        return None
    # Else assume execution id
    for r in runs:
        if str(r.id) == alias or str(r.id).startswith(alias):
            return r
    return None


# ── Plain runtimes ─────────────────────────────────────────────────────

async def _verb_help(args: dict[str, Any], **_: Any) -> dict[str, Any]:
    return {
        "kind": "markdown",
        "body": verb_doc_md(args.get("verb")),
    }


async def _verb_show(*, args: dict[str, Any], db: AsyncSession, agent: Any,
                     user: Any) -> dict[str, Any]:
    obj = (args.get("object") or "").lower()
    if obj == "workflow":
        return {"kind": "json", "title": "workflow", "body": _get_pipeline_dsl(agent)}
    if obj == "nodes":
        nodes = (agent.model_config_ or {}).get("pipeline_config", {}).get("nodes", [])
        rows = [{"id": n.get("id"), "tool": n.get("tool") or n.get("agent_slug"),
                 "depends_on": n.get("depends_on") or []} for n in nodes]
        return {"kind": "table", "title": "nodes", "rows": rows}
    if obj == "schedule":
        from models.agent_trigger import AgentTrigger
        rows = (await db.execute(
            select(AgentTrigger).where(
                AgentTrigger.agent_id == agent.id,
                AgentTrigger.tenant_id == user.tenant_id,
                AgentTrigger.trigger_type == "schedule",
            )
        )).scalars().all()
        return {"kind": "table", "title": "schedule", "rows": [
            {"name": t.name, "cron": t.cron_expression, "active": bool(t.is_active),
             "next_run_at": t.next_run_at.isoformat() if t.next_run_at else None}
            for t in rows
        ]}
    if obj == "runs":
        from models.execution import Execution
        rows = (await db.execute(
            select(Execution).where(
                Execution.agent_id == agent.id,
                Execution.tenant_id == user.tenant_id,
            ).order_by(desc(Execution.created_at)).limit(15)
        )).scalars().all()
        return {"kind": "table", "title": "runs", "rows": [
            {"id": str(r.id), "status": str(r.status.value if hasattr(r.status, "value") else r.status),
             "duration_ms": r.duration_ms, "created_at": r.created_at.isoformat() if r.created_at else None}
            for r in rows
        ]}
    if obj == "failures":
        from models.pipeline_healing import PipelineRunDiff
        rows = (await db.execute(
            select(PipelineRunDiff).where(
                PipelineRunDiff.pipeline_id == agent.id,
                PipelineRunDiff.tenant_id == user.tenant_id,
            ).order_by(desc(PipelineRunDiff.created_at)).limit(15)
        )).scalars().all()
        return {"kind": "table", "title": "failures", "rows": [
            {"node": r.node_id, "kind": r.node_kind, "target": r.node_target,
             "error_class": r.error_class, "message": (r.error_message or "")[:200],
             "at": r.created_at.isoformat() if r.created_at else None}
            for r in rows
        ]}
    if obj == "patches":
        from models.pipeline_healing import PipelinePatchProposal
        rows = (await db.execute(
            select(PipelinePatchProposal).where(
                PipelinePatchProposal.pipeline_id == agent.id,
                PipelinePatchProposal.tenant_id == user.tenant_id,
            ).order_by(desc(PipelinePatchProposal.created_at)).limit(20)
        )).scalars().all()
        return {"kind": "table", "title": "patches", "rows": [
            {"id": str(r.id)[:8], "title": r.title, "status": str(r.status.value if hasattr(r.status, "value") else r.status),
             "risk": r.risk_level, "confidence": float(r.confidence)}
            for r in rows
        ]}
    if obj == "costs":
        from models.execution import Execution
        rows = (await db.execute(
            select(Execution).where(
                Execution.agent_id == agent.id,
                Execution.tenant_id == user.tenant_id,
            ).order_by(desc(Execution.created_at)).limit(100)
        )).scalars().all()
        total = sum(float(r.cost_usd or 0) for r in rows)
        anth = sum(float(getattr(r, "anthropic_cost", 0) or 0) for r in rows)
        oai = sum(float(getattr(r, "openai_cost", 0) or 0) for r in rows)
        goog = sum(float(getattr(r, "google_cost", 0) or 0) for r in rows)
        other = sum(float(getattr(r, "other_cost", 0) or 0) for r in rows)
        return {"kind": "json", "title": "costs (last 100 runs)", "body": {
            "total_usd": round(total, 4),
            "anthropic_usd": round(anth, 4),
            "openai_usd": round(oai, 4),
            "google_usd": round(goog, 4),
            "other_usd": round(other, 4),
            "avg_per_run": round(total / max(1, len(rows)), 4),
            "samples": len(rows),
        }}
    return {"kind": "error", "body": f"unknown object: '{obj}'"}


async def _verb_describe(*, args: dict[str, Any], agent: Any, **_: Any) -> dict[str, Any]:
    nid = args.get("node")
    nodes = (agent.model_config_ or {}).get("pipeline_config", {}).get("nodes", [])
    for n in nodes:
        if n.get("id") == nid:
            return {"kind": "json", "title": f"node: {nid}", "body": n}
    return {"kind": "error", "body": f"no node '{nid}'"}


async def _verb_diff(*, args: dict[str, Any], db: AsyncSession, agent: Any, user: Any) -> dict[str, Any]:
    from models.execution import Execution
    runs = (await db.execute(
        select(Execution).where(
            Execution.agent_id == agent.id,
            Execution.tenant_id == user.tenant_id,
        ).order_by(desc(Execution.created_at)).limit(20)
    )).scalars().all()
    a = _resolve_run_alias(args.get("a") or "", runs)
    b = _resolve_run_alias(args.get("b") or "", runs)
    if not a or not b:
        return {"kind": "error", "body": "could not resolve both runs"}

    return {"kind": "json", "title": f"diff {args.get('a')} vs {args.get('b')}", "body": {
        "a": {"id": str(a.id), "status": str(a.status), "duration_ms": a.duration_ms,
              "cost_usd": float(a.cost_usd or 0), "output_preview": (a.output_message or "")[:600]},
        "b": {"id": str(b.id), "status": str(b.status), "duration_ms": b.duration_ms,
              "cost_usd": float(b.cost_usd or 0), "output_preview": (b.output_message or "")[:600]},
        "delta": {
            "duration_ms": (a.duration_ms or 0) - (b.duration_ms or 0),
            "cost_usd": round(float(a.cost_usd or 0) - float(b.cost_usd or 0), 4),
        },
    }}


async def _verb_list(*, args: dict[str, Any], db: AsyncSession, agent: Any, user: Any) -> dict[str, Any]:
    cat = (args.get("category") or "").lower()
    if cat == "patches":
        return await _verb_show(args={"object": "patches"}, db=db, agent=agent, user=user)
    if cat == "runs":
        return await _verb_show(args={"object": "runs"}, db=db, agent=agent, user=user)
    if cat == "history":
        from models.agent_revision import AgentRevision
        rows = (await db.execute(
            select(AgentRevision).where(
                AgentRevision.agent_id == agent.id,
            ).order_by(desc(AgentRevision.created_at)).limit(20)
        )).scalars().all()
        return {"kind": "table", "title": "history", "rows": [
            {"version": r.version, "summary": (r.change_summary or "")[:120],
             "at": r.created_at.isoformat() if r.created_at else None}
            for r in rows
        ]}
    return {"kind": "error", "body": f"unknown category: '{cat}'"}


# ── Mutating verbs return a JSON-Patch and an updated DSL.  The router
#    wraps these into a PipelinePatchProposal row + persists.
def _patch_set(path: str, value: Any) -> list[dict[str, Any]]:
    """Build a JSON-Patch for `set <node>.<field> <value>` syntax."""
    if "." not in path:
        return [{"op": "replace", "path": f"/{path}", "value": value}]
    node, field = path.split(".", 1)
    if not node:
        # Root field
        return [{"op": "replace", "path": f"/pipeline_config/{field}", "value": value}]
    return [{"op": "replace", "path": f"/pipeline_config/nodes/by-id={node}/{field}", "value": value}]


def _resolve_node_index(nodes: list[dict[str, Any]], nid: str) -> int:
    for i, n in enumerate(nodes):
        if n.get("id") == nid:
            return i
    raise ValueError(f"no node with id '{nid}'")


def _apply_patches_locally(dsl: dict[str, Any], ops: list[dict[str, Any]]) -> dict[str, Any]:
    """Apply our higher-level patch operations and return the modified DSL."""
    import jsonpatch

    nodes = dsl.get("pipeline_config", {}).get("nodes", [])
    translated: list[dict[str, Any]] = []
    for op in ops:
        path = op.get("path", "")
        # /pipeline_config/nodes/by-id=foo/timeout_seconds → /pipeline_config/nodes/3/timeout_seconds
        if "/by-id=" in path:
            head, tail = path.split("/by-id=", 1)
            tokens = tail.split("/", 1)
            nid = tokens[0]
            rest = "/" + tokens[1] if len(tokens) > 1 else ""
            idx = _resolve_node_index(nodes, nid)
            path = f"{head}/{idx}{rest}"
        translated.append({**op, "path": path})

    return jsonpatch.JsonPatch(translated).apply(copy.deepcopy(dsl))


def build_mutation_patch(verb: str, args: dict[str, Any], dsl: dict[str, Any]) -> dict[str, Any]:
    """Translate a parsed mutating-verb invocation into a JSON-Patch"""
    nodes = dsl.get("pipeline_config", {}).get("nodes", [])
    if verb == "set":
        ops = _patch_set(args["path"], args["value"])
        title = f"set {args['path']} = {args['value']}"
        risk = "low"
    elif verb == "rename":
        old = args["old"]; new = args["new"]
        idx = _resolve_node_index(nodes, old)
        ops = [{"op": "replace", "path": f"/pipeline_config/nodes/{idx}/id", "value": new}]
        for j, n in enumerate(nodes):
            if old in (n.get("depends_on") or []):
                deps = list(n["depends_on"])
                deps[deps.index(old)] = new
                ops.append({"op": "replace", "path": f"/pipeline_config/nodes/{j}/depends_on", "value": deps})
        title = f"rename {old} → {new}"
        risk = "low"
    elif verb == "swap-model":
        nid = args["node"]; model = args["model"]
        idx = _resolve_node_index(nodes, nid)
        ops = [{"op": "replace", "path": f"/pipeline_config/nodes/{idx}/model", "value": model}]
        title = f"swap-model {nid} → {model}"
        risk = "medium"
    elif verb == "add-fallback":
        nid = args["node"]; field = args["field"]; default = args["default"]
        idx = _resolve_node_index(nodes, nid)
        node = nodes[idx]
        mappings = dict(node.get("input_mappings") or {})
        mappings[field] = {"value": default, "is_fallback": True}
        ops = [{"op": "replace", "path": f"/pipeline_config/nodes/{idx}/input_mappings", "value": mappings}]
        title = f"add fallback {nid}.{field} = {default}"
        risk = "low"
    elif verb == "remove":
        nid = args["node"]
        idx = _resolve_node_index(nodes, nid)
        # Refuse if anyone depends on this node
        dependants = [n["id"] for n in nodes if nid in (n.get("depends_on") or [])]
        if dependants:
            raise ValueError(f"cannot remove '{nid}' — depended on by: {', '.join(dependants)}")
        ops = [{"op": "remove", "path": f"/pipeline_config/nodes/{idx}"}]
        title = f"remove node {nid}"
        risk = "high"
    elif verb == "add":
        kind = args["kind"]; name = args["name"]; after = args.get("after")
        new_node: dict[str, Any] = {"id": name}
        if kind == "agent":
            new_node["agent_slug"] = name
        else:
            new_node["tool"] = name
        new_node["arguments"] = {}
        new_node["depends_on"] = [after] if after else []
        ops = [{"op": "add", "path": f"/pipeline_config/nodes/-", "value": new_node}]
        title = f"add {kind} {name}" + (f" after {after}" if after else "")
        risk = "medium"
    else:
        raise ValueError(f"verb '{verb}' is not mutating or has no compiler")

    dsl_after = _apply_patches_locally(dsl, ops)
    return {
        "title": title[:240],
        "rationale": f"Authored via talk-to-workflow shell ({verb}).",
        "confidence": 0.9,
        "risk_level": risk,
        "json_patch": ops,
        "dsl_before": dsl,
        "dsl_after": dsl_after,
    }


# ── Top-level dispatch ─────────────────────────────────────────────────

INSPECT_RUNTIMES: dict[str, Any] = {
    "show": _verb_show,
    "describe": _verb_describe,
    "diff": _verb_diff,
    "list": _verb_list,
    "help": _verb_help,
}

MUTATING_VERBS = {"set", "rename", "swap-model", "add-fallback", "remove", "add", "attach"}
EXECUTE_VERBS = {"run", "replay", "simulate", "branch", "merge", "rollback"}
GOVERN_VERBS = {"watch", "budget", "pin", "unpin", "approve", "reject"}
LEARN_VERBS = {"suggest", "diagnose", "explain", "why"}
