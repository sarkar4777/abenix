from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from engine.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

TRAJECTORY_ROOT = Path(os.environ.get("TRAJECTORY_DIR", "/data/trajectories"))
_WORD_RX = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}")


def _tokens(s: str) -> set[str]:
    return {m.group(0).lower() for m in _WORD_RX.finditer(s or "")}


class RecallTrajectoryTool(BaseTool):
    name = "recall_trajectory"
    description = (
        "Retrieve up to K past trajectories whose stored intent text overlaps the new query. "
        "Use it before planning a multi-step fan-out: if a near-identical question was "
        "previously answered with N successful sub-agent calls, adapt that plan instead "
        "of re-discovering it. Returns each trajectory's intent, the agents that were "
        "invoked, and a short summary of the synthesised brief."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Plain-English description of the new task.",
            },
            "top_k": {"type": "integer", "default": 3, "minimum": 1, "maximum": 10},
            "min_overlap_terms": {
                "type": "integer",
                "default": 2,
                "minimum": 1,
                "maximum": 10,
            },
        },
        "required": ["query"],
    }

    def __init__(self, *, tenant_id: str = "", db_url: str = "") -> None:
        self._tenant_id = (tenant_id or "shared").strip() or "shared"
        self._db_url = db_url

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        query = (arguments.get("query") or "").strip()
        top_k = max(1, int(arguments.get("top_k") or 3))
        min_overlap = max(1, int(arguments.get("min_overlap_terms") or 2))
        if not query:
            return ToolResult(content="query is required", is_error=True)

        q_terms = _tokens(query)
        if not q_terms:
            return ToolResult(content=json.dumps({"matches": []}))

        candidates: list[tuple[int, dict[str, Any]]] = []
        for tenant_dir in (
            TRAJECTORY_ROOT / self._tenant_id,
            TRAJECTORY_ROOT / "shared",
        ):
            if not tenant_dir.exists():
                continue
            for path in tenant_dir.glob("*.json"):
                try:
                    entry = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                intent = str(entry.get("intent") or entry.get("question") or "")
                terms = _tokens(intent)
                overlap = len(q_terms & terms)
                if overlap < min_overlap:
                    continue
                candidates.append((overlap, entry))

        candidates.sort(key=lambda x: (-x[0], -(x[1].get("created_at_epoch") or 0)))
        out = []
        for overlap, entry in candidates[:top_k]:
            out.append(
                {
                    "trajectory_id": entry.get("id"),
                    "intent": entry.get("intent") or entry.get("question"),
                    "agents_invoked": entry.get("agents_invoked") or [],
                    "brief_summary": (entry.get("brief") or "")[:280],
                    "term_overlap": overlap,
                    "created_at": entry.get("created_at"),
                    "approval_id": entry.get("approval_id"),
                    "success_signal": entry.get("success_signal"),
                }
            )
        return ToolResult(content=json.dumps({"matches": out}, default=str))
