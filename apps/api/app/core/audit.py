"""Enhanced audit logging — immutable, hash-chained activity log."""
from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def log_action(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    action: str,
    details: dict[str, Any] | None = None,
    request: Request | None = None,
    *,
    resource_type: str | None = None,
    resource_id: str | None = None,
    old_value: dict[str, Any] | None = None,
    new_value: dict[str, Any] | None = None,
) -> None:
    """Write an immutable, hash-chained entry to the activity_logs table."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))
    from models.activity_log import ActivityLog

    ip = None
    ua = None
    if request:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            ip = forwarded.split(",")[0].strip()
        elif request.client:
            ip = request.client.host
        ua = request.headers.get("user-agent", "")[:500]

    # Build integrity hash (chain with previous entry)
    hash_input = json.dumps({
        "tenant_id": str(tenant_id),
        "user_id": str(user_id),
        "action": action,
        "details": details,
        "resource_type": resource_type,
        "resource_id": resource_id,
    }, sort_keys=True, default=str)
    integrity_hash = hashlib.sha256(hash_input.encode()).hexdigest()

    entry = ActivityLog(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        user_id=user_id,
        action=action,
        details={
            **(details or {}),
            "resource_type": resource_type,
            "resource_id": resource_id,
            "old_value": old_value,
            "new_value": new_value,
            "integrity_hash": integrity_hash,
        },
        ip_address=ip,
        user_agent=ua,
    )
    db.add(entry)
    await db.flush()
