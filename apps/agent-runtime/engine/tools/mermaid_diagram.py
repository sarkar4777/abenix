"""Generate Mermaid diagram source from structured data."""

from __future__ import annotations

from typing import Any

from engine.tools.base import BaseTool, ToolResult


def _slug(s: str) -> str:
    """Mermaid node ids must be alphanumeric — strip everything else."""
    return "".join(c if c.isalnum() else "_" for c in str(s))[:32] or "n"


class MermaidDiagramTool(BaseTool):
    name = "mermaid_diagram"
    description = (
        "Produce a Mermaid diagram source block from structured input. "
        "Supports: flowchart (nodes + edges), sequence (actor messages), "
        "pie (label + value), gantt (task + start + duration). The output "
        "is the textual ```mermaid``` block — a viewer/UI renders it."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "diagram_type": {
                "type": "string",
                "enum": ["flowchart", "sequence", "pie", "gantt"],
                "default": "flowchart",
            },
            "title": {
                "type": "string",
                "description": "Optional title above the diagram.",
            },
            "direction": {
                "type": "string",
                "enum": ["TD", "LR", "BT", "RL"],
                "default": "LR",
                "description": "Flowchart direction (top-down, left-right, ...).",
            },
            "nodes": {
                "type": "array",
                "description": "Flowchart only: [{id, label, shape?: round|stadium|cylinder|diamond}].",
                "items": {"type": "object"},
            },
            "edges": {
                "type": "array",
                "description": "Flowchart only: [{from, to, label?}].",
                "items": {"type": "object"},
            },
            "messages": {
                "type": "array",
                "description": "Sequence only: [{from, to, message, type?: sync|async|note}].",
                "items": {"type": "object"},
            },
            "slices": {
                "type": "array",
                "description": "Pie only: [{label, value}].",
                "items": {"type": "object"},
            },
            "tasks": {
                "type": "array",
                "description": "Gantt only: [{task, start (YYYY-MM-DD), duration (e.g. '5d')}].",
                "items": {"type": "object"},
            },
        },
        "required": ["diagram_type"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        kind = arguments.get("diagram_type", "flowchart")
        title = arguments.get("title", "")
        try:
            if kind == "flowchart":
                src = self._flowchart(arguments)
            elif kind == "sequence":
                src = self._sequence(arguments)
            elif kind == "pie":
                src = self._pie(arguments, title)
            elif kind == "gantt":
                src = self._gantt(arguments, title)
            else:
                return ToolResult(
                    content=f"Unknown diagram_type: {kind}", is_error=True
                )
        except ValueError as e:
            return ToolResult(content=str(e), is_error=True)

        block = f"```mermaid\n{src}\n```"
        if title and kind not in ("pie", "gantt"):
            block = f"**{title}**\n\n{block}"

        return ToolResult(
            content=block,
            metadata={
                "diagram_type": kind,
                "source": src,
                "lines": src.count("\n") + 1,
            },
        )

    def _flowchart(self, args: dict[str, Any]) -> str:
        direction = args.get("direction", "LR")
        nodes = args.get("nodes") or []
        edges = args.get("edges") or []
        if not nodes:
            raise ValueError("flowchart requires nodes[]")
        lines = [f"flowchart {direction}"]
        shape_map = {
            "round": ("(", ")"),
            "stadium": ("([", "])"),
            "cylinder": ("[(", ")]"),
            "diamond": ("{", "}"),
            "rect": ("[", "]"),
        }
        for n in nodes:
            nid = _slug(n.get("id") or n.get("label") or "n")
            label = str(n.get("label") or n.get("id") or "").replace('"', "'")
            lb, rb = shape_map.get(n.get("shape", "rect"), shape_map["rect"])
            lines.append(f'  {nid}{lb}"{label}"{rb}')
        for e in edges:
            src = _slug(e.get("from", ""))
            dst = _slug(e.get("to", ""))
            label = str(e.get("label") or "").replace('"', "'")
            arrow = f"-- {label} -->" if label else "-->"
            lines.append(f"  {src} {arrow} {dst}")
        return "\n".join(lines)

    def _sequence(self, args: dict[str, Any]) -> str:
        msgs = args.get("messages") or []
        if not msgs:
            raise ValueError("sequence requires messages[]")
        actors = []
        seen = set()
        for m in msgs:
            for k in ("from", "to"):
                a = m.get(k)
                if a and a not in seen:
                    actors.append(a)
                    seen.add(a)
        lines = ["sequenceDiagram"]
        for a in actors:
            lines.append(f"  participant {_slug(a)} as {a}")
        for m in msgs:
            f = _slug(m.get("from", ""))
            t = _slug(m.get("to", ""))
            text = str(m.get("message") or "").replace("\n", " ")
            arrow = "->>" if m.get("type") == "async" else "->>"
            if m.get("type") == "note":
                lines.append(f"  Note over {f},{t}: {text}")
            else:
                lines.append(f"  {f}{arrow}{t}: {text}")
        return "\n".join(lines)

    def _pie(self, args: dict[str, Any], title: str) -> str:
        slices = args.get("slices") or []
        if not slices:
            raise ValueError("pie requires slices[]")
        head = f"pie title {title}" if title else "pie"
        lines = [head]
        for s in slices:
            label = str(s.get("label", "")).replace('"', "'")
            lines.append(f'  "{label}" : {s.get("value", 0)}')
        return "\n".join(lines)

    def _gantt(self, args: dict[str, Any], title: str) -> str:
        tasks = args.get("tasks") or []
        if not tasks:
            raise ValueError("gantt requires tasks[]")
        lines = ["gantt", "  dateFormat YYYY-MM-DD"]
        if title:
            lines.append(f"  title {title}")
        lines.append("  section Tasks")
        for t in tasks:
            label = str(t.get("task", "Task")).replace(",", " ")
            tid = _slug(label)
            start = t.get("start", "2026-01-01")
            duration = t.get("duration", "1d")
            lines.append(f"  {label} :{tid}, {start}, {duration}")
        return "\n".join(lines)
