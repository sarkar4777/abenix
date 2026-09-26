"""Shared FastAPI dependencies for every PharmaVigil router."""
from __future__ import annotations

import os
import uuid

from fastapi import HTTPException, Request

from abenix_sdk import Abenix, ActingSubject

from app.core.store import CaseStore

DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"
ASSESS_PIPELINE_SLUG = os.environ.get("PV_PIPELINE_SLUG", "pharmavigil-assess")
ASSESS_WAIT_SECONDS = int(os.environ.get("PV_WAIT_TIMEOUT_SECONDS", "900"))


def get_store(request: Request) -> CaseStore:
    store = getattr(request.app.state, "store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="case store not initialised")
    return store


def get_tenant_id(request: Request) -> str:
    raw = request.headers.get("X-Tenant-Id") or DEFAULT_TENANT_ID
    try:
        uuid.UUID(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="X-Tenant-Id must be a uuid")
    return raw


def get_subject(request: Request) -> ActingSubject:
    """Stamp the run with the PharmaVigil user who triggered it.

    Abenix records this on the Execution row, so a case assessed by a safety
    scientist is attributable to them rather than to a shared service account.
    """
    user = request.headers.get("X-Forwarded-User") or "pharmavigil-ui"
    return ActingSubject(subject_type="pharmavigil", subject_id=user)


def get_sdk() -> Abenix:
    """The only way this app talks to Abenix.

    Every call goes through the SDK — no raw HTTP to the platform anywhere in
    this codebase. The SDK handles auth, the acting-subject header, retries
    and the response envelope, and vendoring one copy per app keeps the
    behaviour identical across all seven.
    """
    # The transport timeout has to outlast the pipeline wait. The SDK
    # defaults to 120s while an assessment runs for two to four minutes, so
    # the default cuts the connection on a run that is still going and the
    # app records a bare httpx.ReadTimeout with no message.
    return Abenix(
        base_url=os.environ.get("ABENIX_API_URL", "http://localhost:8000"),
        api_key=os.environ.get("PHARMAVIGIL_ABENIX_API_KEY", ""),
        timeout=float(os.environ.get("PV_SDK_TIMEOUT_SECONDS", str(ASSESS_WAIT_SECONDS + 60))),
    )
