"""Reviewing a draft: edit it, then send, ask the customer, or escalate."""

from __future__ import annotations

from typing import Any, Awaitable, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core import reviews
from app.core.reviews import ReviewRefused
from app.core.store import EmailStore
from app.routers._deps import detail, get_store, ok

router = APIRouter(prefix="/api/qq/emails", tags=["qq-reviews"])


class DraftIn(BaseModel):
    subject: str = Field(min_length=1, max_length=500)
    greeting: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1, max_length=20000)
    closing: str = Field(min_length=1, max_length=1000)


class ReviewIn(BaseModel):
    action: Literal["send", "ask", "escalate"]
    # Required for ask and escalate. The "Reviewed by <name>" the app puts in
    # front of it in Abenix doesn't count as the note.
    note: str = Field(default="", max_length=4000)


async def _fresh(store: EmailStore, email_id: str) -> dict[str, Any]:
    record = await store.get(email_id)
    if record is None:
        raise HTTPException(status_code=404, detail="email not found")
    return ok(detail(record, [r["id"] for r in await store.list()]))


async def _run(store: EmailStore, email_id: str, work: Awaitable[None]) -> dict[str, Any]:
    try:
        await work
    except KeyError:
        raise HTTPException(status_code=404, detail="email not found")
    except ReviewRefused as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc))
    return await _fresh(store, email_id)


@router.put("/{email_id}/draft")
async def save_draft(email_id: str, body: DraftIn, store: EmailStore = Depends(get_store)) -> dict[str, Any]:
    """Save the reviewer's edits. The recipient can't be changed."""
    return await _run(store, email_id, reviews.save_edits(store, email_id, body.model_dump()))


@router.delete("/{email_id}/draft/edits")
async def revert_draft(email_id: str, store: EmailStore = Depends(get_store)) -> dict[str, Any]:
    return await _run(store, email_id, reviews.revert_edits(store, email_id))


@router.post("/{email_id}/review")
async def review(email_id: str, body: ReviewIn, store: EmailStore = Depends(get_store)) -> dict[str, Any]:
    """Send, ask the customer (the app redrafts from the note), or escalate."""
    return await _run(store, email_id, reviews.review(store, email_id, body.action, body.note))


@router.post("/{email_id}/raise-review")
async def raise_review(email_id: str, store: EmailStore = Depends(get_store)) -> dict[str, Any]:
    """Raise the review again after it expired, or after raising it failed."""
    return await _run(store, email_id, reviews.raise_again(store, email_id))
