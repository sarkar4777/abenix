"""Semantic diff between two pieces of text or two structured objects."""
from __future__ import annotations

import difflib
import json
import re
from typing import Any

from engine.tools.base import BaseTool, ToolResult


def _split_paragraphs(text: str) -> list[str]:
    blocks = re.split(r"\n\s*\n", text.strip())
    return [b.strip() for b in blocks if b.strip()]


def _diff_text(a: str, b: str, label_a: str, label_b: str) -> dict[str, Any]:
    a_para = _split_paragraphs(a)
    b_para = _split_paragraphs(b)
    matcher = difflib.SequenceMatcher(None, a_para, b_para, autojunk=False)
    added: list[str] = []
    removed: list[str] = []
    changed: list[dict[str, str]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "insert":
            added.extend(b_para[j1:j2])
        elif tag == "delete":
            removed.extend(a_para[i1:i2])
        elif tag == "replace":
            for i, j in zip(range(i1, i2), range(j1, j2)):
                changed.append({"before": a_para[i], "after": b_para[j]})
            if (i2 - i1) > (j2 - j1):
                removed.extend(a_para[i1 + (j2 - j1) : i2])
            elif (j2 - j1) > (i2 - i1):
                added.extend(b_para[j1 + (i2 - i1) : j2])
    udiff = list(difflib.unified_diff(
        a.splitlines(), b.splitlines(),
        fromfile=label_a, tofile=label_b, lineterm="",
    ))
    return {
        "kind": "text",
        "added_paragraphs": added,
        "removed_paragraphs": removed,
        "changed_paragraphs": changed,
        "unified_diff": "\n".join(udiff[:400]),
        "similarity_ratio": round(matcher.ratio(), 4),
    }


def _diff_json(a: Any, b: Any, path: str = "") -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if type(a) != type(b):
        out.append({"op": "type_changed", "path": path or "/", "before": a, "after": b})
        return out
    if isinstance(a, dict):
        a_keys, b_keys = set(a), set(b)
        for k in sorted(a_keys - b_keys):
            out.append({"op": "removed", "path": f"{path}/{k}", "before": a[k]})
        for k in sorted(b_keys - a_keys):
            out.append({"op": "added",   "path": f"{path}/{k}", "after": b[k]})
        for k in sorted(a_keys & b_keys):
            out.extend(_diff_json(a[k], b[k], f"{path}/{k}"))
    elif isinstance(a, list):
        for i in range(min(len(a), len(b))):
            out.extend(_diff_json(a[i], b[i], f"{path}[{i}]"))
        for i in range(len(b), len(a)):
            out.append({"op": "removed", "path": f"{path}[{i}]", "before": a[i]})
        for i in range(len(a), len(b)):
            out.append({"op": "added",   "path": f"{path}[{i}]", "after": b[i]})
    elif a != b:
        out.append({"op": "changed", "path": path or "/", "before": a, "after": b})
    return out


class SemanticDiffTool(BaseTool):
    name = "semantic_diff"
    description = (
        "Diff two strings or two JSON objects, producing structured "
        "add/remove/change records. Text mode also returns a unified "
        "diff + similarity ratio. Use this BEFORE asking an LLM 'what "
        "changed' — it cuts the LLM's input down by 10x."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "mode": {"type": "string", "enum": ["text", "json"], "default": "text"},
            "left": {"description": "Original (text or JSON object)."},
            "right": {"description": "Updated (text or JSON object)."},
            "label_left": {"type": "string", "default": "v1"},
            "label_right": {"type": "string", "default": "v2"},
        },
        "required": ["left", "right"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        mode = arguments.get("mode", "text")
        left = arguments.get("left")
        right = arguments.get("right")
        if left is None or right is None:
            return ToolResult(content="left and right are both required", is_error=True)

        if mode == "json":
            # Accept either dict/list or a JSON string.
            if isinstance(left, str):
                try: left = json.loads(left)
                except Exception as e: return ToolResult(content=f"left is not valid JSON: {e}", is_error=True)
            if isinstance(right, str):
                try: right = json.loads(right)
                except Exception as e: return ToolResult(content=f"right is not valid JSON: {e}", is_error=True)
            ops = _diff_json(left, right)
            adds = [o for o in ops if o["op"] == "added"]
            rems = [o for o in ops if o["op"] == "removed"]
            chgs = [o for o in ops if o["op"] in ("changed", "type_changed")]
            lines = [
                f"Semantic JSON diff — {len(ops)} change(s)",
                f"  {len(adds)} added, {len(rems)} removed, {len(chgs)} modified",
                "",
            ]
            for o in ops[:50]:
                if o["op"] == "added":
                    lines.append(f"  + {o['path']} = {json.dumps(o['after'])[:200]}")
                elif o["op"] == "removed":
                    lines.append(f"  - {o['path']} = {json.dumps(o['before'])[:200]}")
                else:
                    lines.append(
                        f"  ~ {o['path']}: {json.dumps(o['before'])[:80]} -> {json.dumps(o['after'])[:80]}"
                    )
            return ToolResult(content="\n".join(lines), metadata={"ops": ops, "kind": "json"})

        # text
        if not isinstance(left, str) or not isinstance(right, str):
            return ToolResult(content="text mode needs left/right as strings", is_error=True)
        result = _diff_text(left, right, arguments.get("label_left", "v1"),
                                       arguments.get("label_right", "v2"))
        lines = [
            f"Semantic text diff — similarity {result['similarity_ratio']:.2%}",
            f"  + {len(result['added_paragraphs'])} paragraph(s) added",
            f"  - {len(result['removed_paragraphs'])} paragraph(s) removed",
            f"  ~ {len(result['changed_paragraphs'])} paragraph(s) modified",
            "",
        ]
        for p in result["added_paragraphs"][:6]:
            lines.append(f"+ {p[:300]}")
        for p in result["removed_paragraphs"][:6]:
            lines.append(f"- {p[:300]}")
        for c in result["changed_paragraphs"][:6]:
            lines.append(f"~ before: {c['before'][:200]}")
            lines.append(f"  after:  {c['after'][:200]}")
        return ToolResult(content="\n".join(lines), metadata=result)
