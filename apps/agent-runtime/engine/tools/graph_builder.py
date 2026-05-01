"""graph_builder — generic DAG/graph construction tool."""
from __future__ import annotations

import json
from collections import defaultdict, deque
from typing import Any

from engine.tools.base import BaseTool, ToolResult


class GraphBuilderTool(BaseTool):
    name = "graph_builder"
    description = (
        "Build a structured graph (DAG) from nodes and edges. Returns a "
        "visualization-ready JSON with layout hints, cycle detection, and "
        "topological ordering. Use for dependency graphs, provenance chains, "
        "workflow diagrams, or any entity-relationship map."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Graph title (shown in the header).",
            },
            "nodes": {
                "type": "array",
                "description": "List of graph nodes.",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "label": {"type": "string"},
                        "type": {
                            "type": "string",
                            "description": "Node category for color-coding (e.g. 'electricity', 'payment', 'event').",
                        },
                        "data": {
                            "type": "object",
                            "description": "Arbitrary key-value data attached to this node.",
                        },
                    },
                    "required": ["id", "label"],
                },
            },
            "edges": {
                "type": "array",
                "description": "List of directed edges.",
                "items": {
                    "type": "object",
                    "properties": {
                        "from": {"type": "string", "description": "Source node ID."},
                        "to": {"type": "string", "description": "Target node ID."},
                        "label": {"type": "string", "description": "Edge label (optional)."},
                    },
                    "required": ["from", "to"],
                },
            },
            "layout": {
                "type": "string",
                "description": "Layout algorithm hint: 'auto' (topological), 'horizontal', 'vertical', 'radial'.",
                "default": "auto",
            },
        },
        "required": ["title", "nodes", "edges"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        title = arguments.get("title", "Untitled Graph")
        raw_nodes = arguments.get("nodes") or []
        raw_edges = arguments.get("edges") or []
        layout = arguments.get("layout", "auto")

        if not raw_nodes:
            return ToolResult(content="At least one node is required.", is_error=True)

        node_ids = {n["id"] for n in raw_nodes}
        nodes = []
        for n in raw_nodes:
            nodes.append({
                "id": n["id"],
                "label": n.get("label", n["id"]),
                "type": n.get("type", "default"),
                "data": n.get("data") or {},
            })

        edges = []
        warnings = []
        for e in raw_edges:
            src, tgt = e.get("from", ""), e.get("to", "")
            if src not in node_ids:
                warnings.append(f"edge source '{src}' not in nodes — skipped")
                continue
            if tgt not in node_ids:
                warnings.append(f"edge target '{tgt}' not in nodes — skipped")
                continue
            edges.append({
                "from": src,
                "to": tgt,
                "label": e.get("label", ""),
            })

        # Detect cycles via Kahn's algorithm
        in_degree: dict[str, int] = defaultdict(int)
        adj: dict[str, list[str]] = defaultdict(list)
        for e in edges:
            adj[e["from"]].append(e["to"])
            in_degree[e["to"]] += 1
        for nid in node_ids:
            in_degree.setdefault(nid, 0)

        queue = deque(nid for nid, deg in in_degree.items() if deg == 0)
        topo_order = []
        while queue:
            nid = queue.popleft()
            topo_order.append(nid)
            for neighbor in adj[nid]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        has_cycle = len(topo_order) < len(node_ids)

        # Assign levels (longest path from roots) for layout
        levels: dict[str, int] = {}
        for nid in topo_order:
            levels[nid] = 0
        for nid in topo_order:
            for neighbor in adj[nid]:
                if levels.get(neighbor, 0) < levels.get(nid, 0) + 1:
                    levels[neighbor] = levels[nid] + 1

        # Group nodes by type for stats
        type_counts: dict[str, int] = defaultdict(int)
        for n in nodes:
            type_counts[n["type"]] += 1

        # Enrich nodes with layout info
        for n in nodes:
            n["level"] = levels.get(n["id"], 0)

        graph = {
            "title": title,
            "nodes": nodes,
            "edges": edges,
            "layout": layout,
            "stats": {
                "node_count": len(nodes),
                "edge_count": len(edges),
                "has_cycle": has_cycle,
                "max_depth": max(levels.values()) if levels else 0,
                "type_counts": dict(type_counts),
                "topological_order": topo_order if not has_cycle else [],
            },
            "warnings": warnings,
        }

        return ToolResult(
            content=json.dumps(graph),
            is_error=False,
            metadata={
                "node_count": len(nodes),
                "edge_count": len(edges),
                "has_cycle": has_cycle,
            },
        )
