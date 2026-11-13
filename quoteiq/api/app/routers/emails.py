"""The inbox: the example emails, processing them, retry and reset.

Processing returns at once (202) and runs the pipeline in the background; the
web app polls the email for progress.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.core import reviews, runs
from app.core.abenix import spawn
from app.core.store import STATUSES, EmailStore
from app.routers._deps import detail, get_store, ok, row

router = APIRouter(prefix="/api/qq", tags=["qq-emails"])

LIST_FILTERS = set(STATUSES) | {"waiting", "processing"}


@router.get("/emails")
async def list_emails(status: str | None = None, store: EmailStore = Depends(get_store)) -> dict[str, Any]:
    if status and status not in LIST_FILTERS:
        raise HTTPException(status_code=422, detail=f"status must be one of {', '.join(sorted(LIST_FILTERS))}")
    records = await store.list()
    return ok([row(r) for r in records if not status or r["status"] == status])


@router.get("/stats")
async def stats(store: EmailStore = Depends(get_store)) -> dict[str, Any]:
    return ok(await store.stats())


@router.get("/emails/{email_id}")
async def get_email(email_id: str, store: EmailStore = Depends(get_store)) -> dict[str, Any]:
    record = await store.get(email_id)
    if record is None:
        raise HTTPException(status_code=404, detail="email not found")
    ids = [r["id"] for r in await store.list()]
    return ok(detail(record, ids))


@router.post("/process-next", status_code=202)
async def process_next(store: EmailStore = Depends(get_store)) -> dict[str, Any]:
    """Send the next waiting email to the pipeline. Several can run side by side."""
    claimed = await store.claim_next()
    if claimed is None:
        raise HTTPException(status_code=409, detail="every email has been processed")
    spawn(runs.process_email(store, claimed["id"], claimed["job"]), name=f"process:{claimed['id']}")
    return ok(row(claimed))


@router.post("/emails/{email_id}/process", status_code=202)
async def process_email(email_id: str, store: EmailStore = Depends(get_store)) -> dict[str, Any]:
    """Send this email to the pipeline, if it is still waiting."""
    try:
        claimed = await store.claim(email_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="email not found")
    if claimed is None:
        record = await store.get(email_id)
        raise HTTPException(status_code=409, detail=f"this email is already {record['status'].replace('_', ' ')}")
    spawn(runs.process_email(store, email_id, claimed["job"]), name=f"process:{email_id}")
    return ok(row(claimed))


@router.post("/emails/{email_id}/retry", status_code=202)
async def retry(email_id: str, store: EmailStore = Depends(get_store)) -> dict[str, Any]:
    try:
        updated = await runs.retry(store, email_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="email not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return ok(row(updated))


@router.post("/reset")
async def reset(store: EmailStore = Depends(get_store)) -> dict[str, Any]:
    """Clear every result. Open reviews are denied in Abenix with a reset note."""
    return ok(await reviews.reset(store))
