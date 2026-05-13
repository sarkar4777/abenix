from __future__ import annotations

import json
import os
import re
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TRAJECTORY_ROOT = Path(os.environ.get("WINGMAN_TRAJECTORY_DIR", "/data/wingman-trajectories"))
TENANT = os.environ.get("WINGMAN_TRAJECTORY_TENANT", "shared")
_WORD_RX = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}")


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _atomic_write(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, default=str)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise


def _tokens(s: str) -> set[str]:
    return {m.group(0).lower() for m in _WORD_RX.finditer(s or "")}


def write_trajectory(record: dict[str, Any]) -> str:
    tid = record.get("id") or f"traj-{uuid.uuid4().hex[:12]}"
    record["id"] = tid
    record.setdefault("created_at", _now_iso())
    record["created_at_epoch"] = time.time()
    _atomic_write(TRAJECTORY_ROOT / TENANT / f"{tid}.json", record)
    return tid


def list_trajectories(limit: int = 50) -> list[dict[str, Any]]:
    folder = TRAJECTORY_ROOT / TENANT
    if not folder.exists():
        return []
    items: list[dict[str, Any]] = []
    for path in sorted(folder.glob("*.json"), key=lambda p: -p.stat().st_mtime)[:limit]:
        try:
            items.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    return items


def search_trajectories(query: str, top_k: int = 5) -> list[dict[str, Any]]:
    q_terms = _tokens(query)
    if not q_terms:
        return []
    scored: list[tuple[int, dict[str, Any]]] = []
    for t in list_trajectories(limit=200):
        intent = str(t.get("intent") or "")
        score = len(q_terms & _tokens(intent))
        if score > 0:
            scored.append((score, t))
    scored.sort(key=lambda x: (-x[0], -(x[1].get("created_at_epoch") or 0)))
    return [t for _, t in scored[:top_k]]


def get_trajectory(trajectory_id: str) -> dict[str, Any] | None:
    p = TRAJECTORY_ROOT / TENANT / f"{trajectory_id}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def attach_outcome(trajectory_id: str, *, approval_id: str | None = None, success_signal: float | None = None, note: str | None = None) -> bool:
    obj = get_trajectory(trajectory_id)
    if obj is None:
        return False
    if approval_id is not None:
        obj["approval_id"] = approval_id
    if success_signal is not None:
        obj["success_signal"] = success_signal
    if note is not None:
        obj["outcome_note"] = note
    obj["outcome_updated_at"] = _now_iso()
    _atomic_write(TRAJECTORY_ROOT / TENANT / f"{trajectory_id}.json", obj)
    return True
