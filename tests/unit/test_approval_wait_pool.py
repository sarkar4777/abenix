"""A long-poll on an approval gives its pooled connection back between reads."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.routers import approvals as router
from models.approval import Approval, ApprovalStatus

pytestmark = pytest.mark.asyncio

TENANT = uuid.uuid4()


class _Session:
    def __init__(self, rows):
        self.rows = list(rows)
        self.open = False
        self.closes = 0
        self.reads_while_open = 0

    async def execute(self, _stmt):
        if self.open:
            self.reads_while_open += 1
        self.open = True
        row = self.rows.pop(0) if len(self.rows) > 1 else self.rows[0]
        return SimpleNamespace(scalar_one_or_none=lambda: row)

    async def close(self):
        self.open = False
        self.closes += 1


def _approval(status):
    now = datetime.now(timezone.utc)
    return Approval(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        title="Reroute HT4",
        status=status,
        expires_at=now + timedelta(hours=1),
        created_at=now,
    )


async def _no_sleep(_s):
    return None


async def test_wait_closes_session_between_polls():
    pending = _approval(ApprovalStatus.pending)
    done = _approval(ApprovalStatus.approved)
    db = _Session([pending, pending, done])
    user = SimpleNamespace(id=uuid.uuid4(), tenant_id=TENANT)
    with patch.object(router.asyncio, "sleep", _no_sleep):
        res = await router.wait_for_approval(
            str(pending.id), timeout_seconds=30, user=user, db=db
        )
    assert res.status_code == 200
    assert json.loads(res.body)["data"]["status"] == "approved"
    assert db.closes == 2
    assert db.reads_while_open == 0
