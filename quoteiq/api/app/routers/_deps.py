"""Shared pieces for every QuoteIQ router."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request

from app.core.config import settings
from app.core.store import EmailStore, current_draft


def get_store(request: Request) -> EmailStore:
    store = getattr(request.app.state, "store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="email store not initialised")
    return store


def ok(data: Any) -> dict[str, Any]:
    return {"data": data, "error": None, "meta": None}


def row(record: dict[str, Any]) -> dict[str, Any]:
    """One inbox row."""
    run = record.get("run") or {}
    draft = current_draft(record) or {}
    return {
        "id": record["id"],
        "status": record["status"],
        "review": record.get("review"),
        "from_name": record["from_name"],
        "from_email": record["from_email"],
        "subject": record["subject"],
        "line_count": len(record.get("lines") or []) or None,
        "lines_done": run.get("lines_done") if record["status"] == "processing" else None,
        "outcome": record.get("outcome"),
        "edited": bool(draft.get("edited")),
        "error": record.get("error"),
        "processed_at": record.get("processed_at"),
    }


def detail(record: dict[str, Any], ids: list[str]) -> dict[str, Any]:
    """The full record for the email page, with its neighbours and run links."""
    out = {k: v for k, v in record.items() if k != "job"}
    index = ids.index(record["id"]) if record["id"] in ids else -1
    out["prev_id"] = ids[index - 1] if index > 0 else None
    out["next_id"] = ids[index + 1] if 0 <= index < len(ids) - 1 else None
    out["run_url"] = settings.run_url((record.get("run") or {}).get("execution_id"))
    out["drafts"] = [{**d, "run_url": settings.run_url(d.get("execution_id"))} for d in record.get("drafts") or []]
    out["staff_name"] = settings.staff_name
    out["abenix_web_url"] = settings.abenix_web_url.rstrip("/")
    return out
