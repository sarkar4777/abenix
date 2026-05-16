"""Shared FastAPI dependencies for every ResolveAI router."""
from __future__ import annotations

import os
import uuid
from typing import Any

from fastapi import Depends, HTTPException, Request

from abenix_sdk import ActingSubject, Abenix

from app.core.store import CaseStore


DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"


def get_store(request: Request) -> CaseStore:
    """Return the single process-wide store (in-memory or Postgres)."""
    store = getattr(request.app.state, "store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="case store not initialised")
    return store


def get_tenant_id(request: Request) -> str:
    """Extract the caller's tenant id."""
    raw = request.headers.get("X-Tenant-Id") or DEFAULT_TENANT_ID
    try:
        uuid.UUID(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="X-Tenant-Id must be a uuid")
    return raw


def get_subject(request: Request) -> ActingSubject:
    """Build an ActingSubject header for SDK delegation."""
    user = request.headers.get("X-Forwarded-User") or "resolveai-ui"
    return ActingSubject(subject_type="resolveai", subject_id=user)


def get_sdk() -> Abenix:
    """Instantiate the Abenix SDK client for one request."""
    key = os.environ.get("RESOLVEAI_ABENIX_API_KEY", "")
    if not key:
        raise HTTPException(
            status_code=503,
            detail="RESOLVEAI_ABENIX_API_KEY not set — api can't delegate to Abenix",
        )
    base = os.environ.get("ABENIX_API_URL", "http://localhost:8000")
    return Abenix(api_key=key, base_url=base, timeout=300.0)


async def _maybe(coro_or_value: Any) -> Any:
    """Await if awaitable, else return as-is."""
    if hasattr(coro_or_value, "__await__"):
        return await coro_or_value
    return coro_or_value
